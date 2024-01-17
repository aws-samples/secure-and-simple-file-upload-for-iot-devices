# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.
import os.path

from awscrt import mqtt
from awsiot import mqtt_connection_builder
import sys
import threading
import uuid
import json
import argparse
import hashlib
import requests
from datetime import datetime

# MQTT topics
TOPIC_BASE = "awsSample/iotDocUpload"

# Callback when the connection successfully connects
def on_connection_success(connection, callback_data):
    assert isinstance(callback_data, mqtt.OnConnectionSuccessData)
    print("Connection Successful with return code: {} session present: {}".format(callback_data.return_code,
                                                                                  callback_data.session_present))


# Callback when a connection attempt fails
def on_connection_failure(connection, callback_data):
    assert isinstance(callback_data, mqtt.OnConnectionFailureData)
    print("Connection failed with error code: {}".format(callback_data.error))


# Callback when a connection has been disconnected or shutdown successfully
def on_connection_closed(connection, callback_data):
    print("Connection closed")


# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    print("Connection interrupted. error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    print("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        print("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
    resubscribe_results = resubscribe_future.result()
    print("Resubscribe results: {}".format(resubscribe_results))

    for topic, qos in resubscribe_results['topics']:
        if qos is None:
            sys.exit("Server rejected resubscribe to topic: {}".format(topic))


def initialise(args, receiver_class):
    """
    Initialise an MQTT connection and subscribe to the relevant topics
    :param args: the arguments passed in the command line
    :return: the MQTT connection
    """
    # Create a MQTT connection from the command line args
    mqtt_connection = mqtt_connection_builder.mtls_from_path(
        endpoint=args.endpoint,
        port=args.port,
        cert_filepath=args.cert,
        pri_key_filepath=args.key,
        ca_filepath=args.root_ca,
        on_connection_interrupted=on_connection_interrupted,
        on_connection_resumed=on_connection_resumed,
        client_id=args.client_id,
        clean_session=True,
        keep_alive_secs=30,
        on_connection_success=on_connection_success,
        on_connection_failure=on_connection_failure,
        on_connection_closed=on_connection_closed,
    )
    print("Connecting to endpoint with client ID {}".format(args.client_id))
    connect_future = mqtt_connection.connect()
    connect_future.result()
    print("Connected!")

    # Subscribe to response topic
    response_topic = "{}/{}/{}/#".format(TOPIC_BASE, "docUpldResp", args.client_id)
    print("Subscribing to topic '{}'...".format(response_topic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=response_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=receiver_class.on_response_received)

    subscribe_result = subscribe_future.result()
    print("Subscribed with {}".format(str(subscribe_result['qos'])))

    ack_topic = "{}/{}/{}/#".format(TOPIC_BASE, "docUpldAck", args.client_id)
    print("Subscribing to topic '{}'...".format(ack_topic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=ack_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=receiver_class.on_ack_received)

    subscribe_result = subscribe_future.result()
    print("Subscribed with {}".format(str(subscribe_result['qos'])))

    return mqtt_connection


def make_request(args, connection):
    """
    Make a request to upload a new archive
    :param connection: The MQTT connection
    :param args: command line arguments
    :return: nothing
    """""
    if not os.path.isfile(args.archive_path):
        print("File {} does not exist".format(args.archive_path))
        return
    if args.bad_md5 is not True:
        md5 = hashlib.md5(open(args.archive_path, 'rb').read()).hexdigest()
    else:
        md5 = "11111111111111111111111111111111"
    payload = {
        'requestUuid': str(uuid.uuid4()),
        'md5': md5
    }
    if args.bad_payload is True:
        payload.pop('md5')
    topic = "{}/{}/{}/{}".format(TOPIC_BASE, "docUpldReq", args.client_id, datetime.utcnow().isoformat())
    print("Publishing message to topic '{}': {}".format(topic, payload))
    publish_future, packet_id = connection.publish(
        topic=topic,
        payload=json.dumps(payload),
        qos=mqtt.QoS.AT_LEAST_ONCE)
    publish_result = publish_future.result()
    print("Published to topic {} with result: {}".format(topic, publish_result))


class ReceiveCallbacks(object):
    def __init__(self, args, timeout=5):
        self.args = args
        # Events tracking
        self.received_response = threading.Event()
        self.received_ack = threading.Event()
        self.timeout = timeout

    def on_response_received(self, topic, payload, dup, qos, retain, **kwargs):
        print("Received RESPONSE message from topic '{}': {}".format(topic, payload))
        data = json.loads(payload)
        ruuid = data.get('requestUuid')
        url = data.get('url')
        exp = data.get('expiration')
        headers = data.get('headers')
        if not url:
            print("Upload request was rejected. The document will not be uploaded.")
        else:
            print("Uploading document {}".format(args.archive_path))
            result = requests.put(url=url, data=open(self.args.archive_path, 'rb'), headers=headers)
            print("Upload result: code={}, content={}".format(result, result.content))
        self.received_response.set()

    def on_ack_received(self, topic, payload, dup, qos, retain, **kwargs):
        print("Received ACK message from topic '{}': {}".format(topic, payload))
        self.received_ack.set()

    def wait_for_responses(self):
        self.received_response.wait(timeout=self.timeout)
        self.received_ack.wait(timeout=self.timeout)


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                          "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
    parser.add_argument("--port", required=False, default=8883, type=int, choices=[8883, 443],
                        help="Specify port. AWS IoT supports 443 and 8883.")
    parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
    parser.add_argument('--key', help="File path to your private key, in PEM format.")
    parser.add_argument('--root_ca', help="File path to root certificate authority, in PEM format. " +
                                          "Necessary if MQTT server uses a certificate that's not already in your trust store.")
    parser.add_argument('--client_id', required=True, help="Client ID for MQTT connection.")
    parser.add_argument("--archive_path", required=True, help="Path to the archive file to upload")
    parser.add_argument("--bad_md5", action=argparse.BooleanOptionalAction, default=False, help="Test for bad MD5 hash")
    parser.add_argument("--bad_payload", action=argparse.BooleanOptionalAction, default=False,
                        help="Test for bad payload")

    args = parser.parse_args()

    receiver = ReceiveCallbacks(args)
    mqtt_connection = initialise(args, receiver)
    make_request(args, mqtt_connection)
    receiver.wait_for_responses()

    print("Disconnecting")
    mqtt_connection.disconnect()
    print("Googbye!")

