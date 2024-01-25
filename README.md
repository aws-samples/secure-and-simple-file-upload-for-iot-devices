# AWS Secure S3 File Upload For Iot Device

Welcome to this project that demonstrates how to easily and securely add the capability for an IoT Device
to upload documents to S3, without having to manage any special credential apart from the normal connection to 
AWS IoT Core. The only functionality the device needs is to publish and subscribe to a few topics, process those and
sue an https PUT method.

## Getting started

The project is split in two parts:
* The cloud-side, using only serverless services. [See cloud-side documentation](app/README.md)
* An example of IoT Client, writen in python and located in the `client` folder.


## Installation

* Follow the instructions in the [cloud-side documentation](app/README.md)
* For running the client:
  * install python if not already done. This project has been tested with python 3.12.
  * pip install requirements
  * create the test archives (they are not created because an archive constitutes a security risk when checked-in):
    ```bash
    cd client/test_data
    bash make_test_data.sh
    cd ../..
    ```

## Usage
* Deploy and configure your cloud infrastructure (with CDK). See [cloud-side documentation](app/README.md).
* Create an AWS IoT thing and download its certificate, private key and CA certificate.
  * Do NOT create policy for the Thing Certificate
  * Add the IoT Thing to the group `uploaderThingGroup`
* Edit the client runner `client/run_test.sh` and modify the configuration section at the top to match your setup.
* Runt the client `bash run_test.sh [1, 2, 3, 4, 5]`

## Support
For support open a ticket in GitHub.

## Roadmap
Nothing new planned for now. Make suggestions!

## Contributing
[See CONTRIBUTING.md](./CONTRIBUTING.ms)


## License
[See LICENSE](./LICENSE)

## Project status
Active support.