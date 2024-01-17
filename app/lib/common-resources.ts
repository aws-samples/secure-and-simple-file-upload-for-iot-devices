import { Duration, RemovalPolicy, Stack} from "aws-cdk-lib";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import * as aws_s3 from "aws-cdk-lib/aws-s3";
import * as aws_iam from "aws-cdk-lib/aws-iam";
import * as aws_kms from "aws-cdk-lib/aws-kms";

export class CommonResources extends Construct {
  public readonly accessLogsS3Bucket: aws_s3.Bucket;
  public readonly encryptionKey: aws_kms.Key;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // The S3 bucket for storing the Access Logs - cannot use a custom key
    this.accessLogsS3Bucket = new aws_s3.Bucket(this, "AccessLogsS3Bucket", {
      versioned: false,
      removalPolicy: RemovalPolicy.RETAIN,
      objectOwnership: aws_s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      publicReadAccess: false,
      blockPublicAccess: aws_s3.BlockPublicAccess.BLOCK_ALL,
      encryption: aws_s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      lifecycleRules: [
        {
          expiration: Duration.days(365),
        },
      ],
    });

    NagSuppressions.addResourceSuppressions(
        this.accessLogsS3Bucket,
        [
          {
            id: "AwsSolutions-S1",
            reason: "Can't add Server Access Log to Log Server.",
          },
        ]
    )

    // Private KMS key
    this.encryptionKey = new aws_kms.Key(this, "encryptionKey", {
      enableKeyRotation: true,
    });

    const aliasName = "s3-file-upload-for-iot-key";
    this.encryptionKey.addAlias(aliasName);
    this.encryptionKey.grantEncryptDecrypt(new aws_iam.AccountRootPrincipal());
    this.encryptionKey.grantEncryptDecrypt(new aws_iam.ServicePrincipal(`logs.${Stack.of(this).region}.amazonaws.com`));
  }
}
