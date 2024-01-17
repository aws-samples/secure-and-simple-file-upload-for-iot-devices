import logging
import sys
import os
import tempfile
import json
from zipfile import ZipFile
from base64 import b16decode

import boto3
import botocore.client
from botocore.client import Config

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger('myLambda')
LOG_LEVEL = str(os.environ["LOG_LEVEL"]).upper()
logger.setLevel(LOG_LEVEL)

STORE_BUCKET_NAME = os.environ["STORE_BUCKET_NAME"]
REQ_KW = os.environ["TOPIC_REQ_KW"]
ACK_KW = os.environ["TOPIC_ACK_KW"]

s3_client = boto3.client('s3',
                         config=Config(signature_version='s3v4')
                         )
iot_client = boto3.client('iot-data')


class InvalidMetadata(Exception):
    pass


def b16low2s(s):
    """
    Decode a string previously encoded with Base16 in lowercase
    :param s: Base16 encoded string
    :return: decoded string
    """
    return b16decode(s, casefold=True).decode('utf-8')


def decode_metadata(metadata):
    """
    Decode the metadata in the S3 object
    :param metadata: a dict of Base16 encoded keys and values
    :return: A dict with keys and values decoded as strings
    """
    decoded_metadata = {}
    for k, v in metadata.items():
        decoded_metadata[b16low2s(k)] = b16low2s(v)
    return decoded_metadata


def check_metadata(mdata):
    """
    Check if the metadata contains the required keys.
    :param mdata: a dict containing the metadata
    :return: True if the metadata is valid, False otherwise
    """
    expected_keys = {'org-mqtt-topic', 'requestUuid'}
    payload_keys = set(mdata.keys())
    is_ok = expected_keys.issubset(payload_keys)
    if is_ok is not True:
        logger.error("The received payload keys: {} does not contain the expected keys: {}"
                     .format(payload_keys, expected_keys))

    return is_ok


def process_dir(extract_path, cu_path, partition_path):
    """
    REcursively process a directory and pushing documents to S3 with a partitioning corresponding to the path below
    the extract_path.
    :param extract_path: The path where the recursive discovery starts
    :param cu_path: the path below the extract_path
    :param partition_path: current the S3 partition path
    :return: None
    """
    abs_cu_path = str(os.path.join(extract_path, cu_path))
    extracted = os.listdir(abs_cu_path)
    logger.debug("List of extracted docs: {}".format(extracted))
    for doc in extracted:
        logger.debug("Processing: {}".format(doc))
        doc_path = os.path.join(abs_cu_path, doc)
        if os.path.isfile(doc_path):
            dest_key = "{}/{}".format(partition_path, os.path.join(cu_path, doc))
            logger.debug(
                "Moving extracted file {} to S3 {}:{}".format(doc_path, STORE_BUCKET_NAME, dest_key))
            s3_client.upload_file(doc_path, STORE_BUCKET_NAME, dest_key)
        elif os.path.isdir(doc_path):
            process_dir(extract_path, str(os.path.join(cu_path, doc)), partition_path)


def lambda_handler(event, context):
    """
    This Lambda function is invoked by Amazon S3 when a new object is created in the Bucket.
    The new object is expected to have been uploaded by an IoT Device, to contain Base16 encoded metadata and to be a
    ZIP archive. This archive will be unzipped to a destination Bucket and the original archive deleted.
    """
    logger.debug("Lambda processing called with: {}".format(event))
    mdata = {}
    for record in event['Records']:
        source_bucket = record['s3']['bucket']['name']
        object_key = record['s3']['object']['key']
        logger.debug("Processing uploaded object: {}".format(object_key))
        try:
            try:
                mdata_encoded = s3_client.head_object(Bucket=source_bucket, Key=object_key)['Metadata']
                logger.debug("Encoded metadata: {}".format(mdata_encoded))
                mdata = decode_metadata(mdata_encoded)
                logger.debug("Retrieved metadata: {}".format(mdata))
            except botocore.client.ClientError as e:
                raise InvalidMetadata(e)
            if check_metadata(mdata) is not True:
                raise InvalidMetadata("Missing metadata key(s)")
            # The partition where the archive will be extracted is equal to the MQTT topic
            partition_path = mdata['org-mqtt-topic']
            # Extract the archive and upload each document to S3
            with tempfile.TemporaryDirectory() as d:
                with open("{}/{}".format(d, object_key), mode='wb') as f:
                    logger.debug("Getting object: {}".format(object_key))
                    s3_client.download_fileobj(source_bucket, object_key, f)
                with ZipFile("{}/{}".format(d, object_key), 'r') as zf:
                    logger.debug("Extracting archive object: {}".format(object_key))
                    extract_path = os.path.join(d, 'content')
                    zf.extractall(extract_path)

                process_dir(extract_path, "", partition_path)

            response_topic = mdata['org-mqtt-topic'].replace(REQ_KW, ACK_KW)
            payload = {
                'success': True,
                'requestUuid': mdata['requestUuid']
            }
            logger.info("Publishing success response to topic {} with payload: {}".format(response_topic, payload))
            result = iot_client.publish(
                topic=response_topic,
                qos=1,
                payload=json.dumps(payload)
            )
            logger.debug("Publish result: {}".format(result))
            logger.info("Deleting source file from S3: {}:{}".format(source_bucket, object_key))
            s3_client.delete_object(Bucket=source_bucket, Key=object_key)

        except Exception as e:
            logger.error("Error when processing Uploaded file: {}".format(e))
            if 'org-mqtt-topic' in mdata:
                response_topic = mdata['org-mqtt-topic'].replace(REQ_KW, ACK_KW)
                payload = {
                    'success': False,
                    'requestUuid': mdata.get('requestUuid', 'NotFound')
                }
                logger.info("Publishing failure response to topic {} with payload: {}".format(response_topic, payload))
                result = iot_client.publish(
                    topic=response_topic,
                    qos=1,
                    payload=json.dumps(payload)
                )
                logger.debug("Publish result: {}".format(result))
            else:
                logger.error("Could not send ACK to uploader because metadata key 'org-mqtt-topic' is missing.")
            logger.warning("The object has not been deleted: {}.{}".format(source_bucket, object_key))
            raise
