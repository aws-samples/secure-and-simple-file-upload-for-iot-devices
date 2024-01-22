#! /bin/bash

# Configuration
IOT_ENDPOINT='a3gj3f4h0tbvas-ats.iot.eu-central-1.amazonaws.com'
CERT_PATH='./creds/test_client_01-certificate.pem.crt'
KEY_PATH='./creds/test_client_01-private.pem.key'
ROOT_CA_PATH='./creds/AmazonRootCA1.pem'
CLIENT_ID='test_client_01'
# End configuration

case $1 in

  1) # Success with two files in S3
    python test_client.py --endpoint  $IOT_ENDPOINT\
    --cert  $CERT_PATH\
    --key  $KEY_PATH\
    --root_ca  $ROOT_CA_PATH\
    --client_id  $CLIENT_ID\
    --archive_path './test_data/archive.zip'
    ;;

  2) # Success with files and folders in S3
    python test_client.py --endpoint $IOT_ENDPOINT \
    --cert  $CERT_PATH\
    --key  $KEY_PATH\
    --root_ca  $ROOT_CA_PATH\
    --client_id  $CLIENT_ID\
    --archive_path './test_data/archive_with_tree.zip'
    ;;

  3) # Failure due to corrupted zip archive
    python test_client.py --endpoint $IOT_ENDPOINT \
    --cert  $CERT_PATH\
    --key  $KEY_PATH\
    --root_ca  $ROOT_CA_PATH\
    --client_id  $CLIENT_ID\
    --archive_path './test_data/bad_zip.zip'
    ;;

  4) # Failure due to non-matching md5
    python test_client.py --endpoint $IOT_ENDPOINT \
    --cert  $CERT_PATH\
    --key  $KEY_PATH\
    --root_ca  $ROOT_CA_PATH\
    --client_id  $CLIENT_ID\
    --archive_path './test_data/archive.zip' \
    --bad_md5
    ;;

  5) # Failure due to non-matching payload
    python test_client.py --endpoint $IOT_ENDPOINT \
    --cert  $CERT_PATH\
    --key  $KEY_PATH\
    --root_ca  $ROOT_CA_PATH\
    --client_id  $CLIENT_ID\
    --archive_path './test_data/archive.zip' \
    --bad_payload
    ;;

  *)
    echo "Usage: 'bash run_test.sh [1, 2, 3, 4, 5]'"
    ;;

esac
