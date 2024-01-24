# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import logging
import sys
import os
import time
import json
from base64 import b64encode, b16encode
from binascii import unhexlify
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from botocore.client import Config

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger('myLambda')
LOG_LEVEL = os.environ["LOG_LEVEL"].upper()
logger.setLevel(LOG_LEVEL)

STG_BUCKET = os.environ["STG_BUCKET_NAME"]
REQ_KW = os.environ["TOPIC_REQ_KW"]
RESP_KW = os.environ["TOPIC_RESP_KW"]

# The content type of teh Upload is fixed to ZIP but can be easily made variable
CONTENT_TYPE = "application/zip"

s3_client = boto3.client('s3',
                         config=Config(signature_version='s3v4')
                         )
iot_client = boto3.client('iot-data')


class PayloadException(Exception):
    pass


def is_payload_ok(payload):
    """
    Check if the payload received in the MQTT message contains the right keys
    :param payload: the erceived payload
    :return: True if OK or False
    """
    expected_keys = {'topic', 'requestUuid', 'md5'}
    payload_keys = set(payload.keys())
    diff = expected_keys.difference(payload_keys)
    if diff:
        logger.error("The received payload keys: {} does not contain the expected keys: {}"
                     .format(payload_keys, expected_keys))
        return False
    return True


def md5_to_b64md5(md5):
    """
    Encodes with Base64 - this is requested by S3 MD5 field
    :param md5: the standard md5 hash of the document to be uploaded to S3
    :return: the Base64 encoded md5 as expected by S3
    """
    md5b64 = b64encode(unhexlify(md5)).decode()
    logger.debug("Received md5: '{}' - returning B64 encoded: '{}'".format(md5, md5b64))
    return md5b64


def make_metadata(event_dict):
    """
    Creates a dictionary with any value that we want to store as S3 Metadata
    :param event_dict: the event dictionary as received tby the handler
    :return: metadata dictionary
    """
    metadata = {
        'org-mqtt-topic': event_dict['topic'],
        'requestUuid': event_dict['requestUuid'],
    }
    return metadata


def s2b16low(s):
    """
    Encodes with Base16 and forces resulting encoded string to lower case.
    :param s: The string to be encoded
    :return: Base16 encoded string in lower case
    """
    return b16encode(s.encode('utf-8')).decode('utf-8').lower()


def encode_metadata(metadata):
    """
    It is necessary to encode the metadata because S3 stores it in lower case only, which brings too much
    complexity in the application to make sure that all the metadata has only lower case.
    Base16 was chosen because it uses only a simple alphabet to encode, which is compatible with http headers.
    :param metadata: a dict containing the metadata in clear
    :return: dict of Base16 encoded metadata for keys and values
    """
    encoded_metadata = {}
    for k, v in metadata.items():
        encoded_metadata[s2b16low(k)] = s2b16low(v)
    return encoded_metadata


def get_presigned_url(metadata, content_type, md5, bucket=STG_BUCKET, key=None, expire=900):
    """
    Get a presigned URL from S3
    :param metadata: the metadata dictionary
    :param content_type: content type at file upload time
    :param md5: the md5 of the document to be uploaded
    :param bucket: the bucket name where files need to be uploaded
    :param key: the key of the object in the bucket after upload
    :param expire: How long (seconds) this presigned UTL will be valid for (min: 900)
    :return: dictionary
    """
    METHOD = "put_object"
    if not key:
        key = str(uuid4())

    md5e = md5_to_b64md5(md5)

    params = {
        'Bucket': bucket,
        'Key': key,
        'ContentType': content_type,
        'Metadata': metadata,
        'ContentMD5': md5e,
    }

    try:
        exp_epoch = int((time.time() + expire) * 1000)
        response = s3_client.generate_presigned_url(ClientMethod=METHOD,
                                                    Params=params,
                                                    ExpiresIn=expire)

        return {'md5e': md5e, 'exp': exp_epoch, 'url': response}

    except ClientError as e:
        logger.error("error when getting presigned URL: {}".format(e))
        raise


def make_headers(metadata, content_type, md5_encoded):
    """
    Creates the headers required for S3 upload with the presigned URL. The sender will have to include those headers
    in the PUT request. This is necessary because a presigned URL signature also includes the Headers.
    :param metadata: the metadata dictionary
    :param content_type: the type of document to be uploaded
    :param md5_encoded: the endcoded md5 of the payload to be uploaded
    :return: headers dictionary
    """
    headers = {
        'content-type': content_type,
        'content-md5': md5_encoded,
    }
    for k, v in metadata.items():
        headers['x-amz-meta-' + k] = v
    logger.debug("Prepared headers: {}".format(headers))
    return headers


def lambda_handler(event, context):
    """
    Return an MQTT response message to a request to upload a document.
    Expected event payload:
    {
        'topic': <string>, # The MQTT topic where the request was received
        'requestUuid': <string>, # The original UUID passed by the sender in the request
        'md5': <string>, # The md5 of the document to be uploaded
    }

    The response will contain the following payload:
    {
        'requestUuid': <string>,  # The original UUID passed by the sender in the request
        'url': <string>, # THe presigned URL to use (PUT)
        'expiration': <int>, # Expiration time of the presigned URL in epoch seconds
        'headers': {<dict>, # The headers to include in the PUT request
    }
    """
    logger.info("Received a request to Upload a document: {}".format(event))
    try:
        if is_payload_ok(event) is not True:
            logger.error("Payload not compliant, request ignored\n: {}".format(event))
            raise AttributeError("Non compliant payload")
        metadata = make_metadata(event)
        encoded_metadata = encode_metadata(metadata)
        resp = get_presigned_url(metadata=encoded_metadata, content_type=CONTENT_TYPE, md5=event['md5'])
        headers = make_headers(metadata=encoded_metadata, content_type=CONTENT_TYPE, md5_encoded=resp['md5e'])
        # Respond using the request topic swapping the request keyword for the response one
        response_topic = event['topic'].replace(REQ_KW, RESP_KW)
        payload = {
            'requestUuid': event['requestUuid'],
            'url': resp['url'],
            'expiration': resp['exp'],
            'headers': headers
        }
        logger.debug("Publishing on topic {} the payload {}".format(response_topic, payload))
        result = iot_client.publish(
            topic=response_topic,
            qos=1,
            payload=json.dumps(payload)
        )
        logger.info("Published response to the request with result: {}".format(result))
    except Exception as e:
        logger.error("Got exception when processing Request: {}".format(e))
        payload = {
            'requestUuid': event.get('requestUuid', ""),
            'url': "",
            'expiration': 0,
            'headers': {}
        }
        response_topic = event['topic'].replace(REQ_KW, RESP_KW)
        logger.debug("Publishing on topic {} the payload {}".format(response_topic, payload))
        result = iot_client.publish(
            topic=response_topic,
            qos=1,
            payload=json.dumps(payload)
        )
        logger.info("Published response to the request with result: {}".format(result))
        if not isinstance(e, PayloadException):
            raise
