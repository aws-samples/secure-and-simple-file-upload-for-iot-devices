import {aws_iam, aws_iot, CfnOutput, Duration, RemovalPolicy, Stack} from 'aws-cdk-lib';
import {Construct} from 'constructs';
import * as aws_s3 from "aws-cdk-lib/aws-s3";
import * as aws_kms from "aws-cdk-lib/aws-kms";
import * as aws_logs from "aws-cdk-lib/aws-logs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as LambdaEventSource from 'aws-cdk-lib/aws-lambda-event-sources';
import {NagSuppressions} from "cdk-nag";

export interface FileUploadProps {
    encryptionKey: aws_kms.IKey;
    accessLogsBucket: aws_s3.Bucket;
}

export class FileUpload extends Construct {

    constructor(scope: Construct, id: string, props: FileUploadProps) {
        super(scope, id);

        const encryptionKey = props.encryptionKey;
        const accessLogsBucket = props.accessLogsBucket;

        // Set a few constants for MQTT topics - no ending '/'
        const topicPrefix: string = "awsSample/iotDocUpload";
        const topicRequestSuffix: string = "docUpldReq";
        const topicResponseSuffix: string = "docUpldResp";
        const topicAckSuffix: string = "docUpldAck";

        // The Bucket where documents are temporarily uploaded
        const stagingBucketName = "docsUploadStaging";
        const stagingBucket = new aws_s3.Bucket(this, stagingBucketName, {
            versioned: false,
            encryption: aws_s3.BucketEncryption.KMS,
            encryptionKey: encryptionKey,
            bucketKeyEnabled: true,
            publicReadAccess: false,
            blockPublicAccess: aws_s3.BlockPublicAccess.BLOCK_ALL,
            objectOwnership: aws_s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            serverAccessLogsBucket: accessLogsBucket,
            serverAccessLogsPrefix: stagingBucketName + '/',
            enforceSSL: true,
            lifecycleRules: [
                {
                    abortIncompleteMultipartUploadAfter: Duration.days(1),
                    enabled: true,
                    expiration: Duration.days(7),
                },
            ]
        });

        // The Lambda function responding to Upload requests
        const responseLambdaLogGroup = new aws_logs.LogGroup(this, "response-lambda-log-group", {
            logGroupName: "iot-file-upload/lambda/publishResponse",
            retention: aws_logs.RetentionDays.TWO_MONTHS,
            removalPolicy: RemovalPolicy.RETAIN,
            encryptionKey: encryptionKey,
        });
        const responseLambdaLogsPolicyStatement = new aws_iam.PolicyStatement({
            effect: aws_iam.Effect.ALLOW,
            actions: [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            resources: [`${responseLambdaLogGroup.logGroupArn}`]
        });
        const publishResponsePolicyStatement = new aws_iam.PolicyStatement({
            effect: aws_iam.Effect.ALLOW,
            actions: ["iot:Publish"],
            resources: [`arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicResponseSuffix}/*`]
        });
        const uploadResponseFunctionRole = new aws_iam.Role(this, "uploadResponseFunctionRole", {
            assumedBy: new aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            description: 'Role assumed by a Lambda function responding to Upload requests',
            inlinePolicies: {
                uploadResponseLambdaPolicy: new aws_iam.PolicyDocument({
                    statements: [responseLambdaLogsPolicyStatement, publishResponsePolicyStatement],
                })
            }
        });
        const uploadResponseFunction = new lambda.Function(this, "uploadResponse", {
            environment: {
                LOG_LEVEL: "DEBUG",
                STG_BUCKET_NAME: stagingBucket.bucketName,
                TOPIC_REQ_KW: topicRequestSuffix,
                TOPIC_RESP_KW: topicResponseSuffix,
            },
            role: uploadResponseFunctionRole,
            code: lambda.Code.fromAsset("./function/src/doc_upload_response"),
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "doc_upload_response.lambda_handler",
            environmentEncryption: encryptionKey,
            logGroup: responseLambdaLogGroup
        });
        encryptionKey.grantEncryptDecrypt(uploadResponseFunction);
        stagingBucket.grantReadWrite(uploadResponseFunction);


        // Iot Rule capturing the Upload Requests and invoking the Lambda function for the response
        const iotLogGroup = new aws_logs.LogGroup(this,  "IotRuleUploadResponseLogGroup",
            {
            logGroupName: "iot-file-upload/iot-core/rule",
            retention: aws_logs.RetentionDays.TWO_MONTHS,
            removalPolicy: RemovalPolicy.RETAIN,
            encryptionKey: encryptionKey,
            }
        );
        const iotLogGroupPolicyStatement = new aws_iam.PolicyStatement({
            effect: aws_iam.Effect.ALLOW,
            actions: [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            resources: [`${iotLogGroup.logGroupArn}`]
        });
        const iotRoleUploadRequest = new aws_iam.Role(this, "iotRoleUploadRequest", {
            assumedBy: new aws_iam.ServicePrincipal("iot.amazonaws.com"),
            description: "Role allowing to process Document Upload Requests"
        });
        iotRoleUploadRequest.addToPolicy(iotLogGroupPolicyStatement);
        encryptionKey.grantEncryptDecrypt(iotRoleUploadRequest);
        const uploadRequestRule = new aws_iot.CfnTopicRule(this, "uploadRequestRule", {
            topicRulePayload: {
                sql: `SELECT *, topic() AS topic
                      FROM '${topicPrefix}/${topicRequestSuffix}/#'`,
                actions: [
                    {
                        lambda: {
                            functionArn: uploadResponseFunction.functionArn,
                        },
                    },
                ],
                errorAction: {
                    cloudwatchLogs: {
                        logGroupName: iotLogGroup.logGroupName,
                        roleArn: iotRoleUploadRequest.roleArn,
                    },
                },
                ruleDisabled: false,
                awsIotSqlVersion: "2016-03-23",
            },
            ruleName: `uploadRequestProcessingRule`,
        });
        uploadResponseFunction.addPermission("uploadRequestProcessingPermission", {
            principal: new aws_iam.ServicePrincipal("iot.amazonaws.com"),
            action: "lambda:InvokeFunction",
            sourceArn: uploadRequestRule.attrArn
        });

        // The Bucket where the documents are permanently stored after upload and postprocessing
        const storageBucketName = "docsUploadStorage";
        const storageBucket = new aws_s3.Bucket(this, storageBucketName, {
            versioned: true,
            encryption: aws_s3.BucketEncryption.KMS,
            encryptionKey: encryptionKey,
            bucketKeyEnabled: true,
            publicReadAccess: false,
            blockPublicAccess: aws_s3.BlockPublicAccess.BLOCK_ALL,
            objectOwnership: aws_s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            serverAccessLogsBucket: accessLogsBucket,
            serverAccessLogsPrefix: storageBucketName + '/',
            enforceSSL: true,
            intelligentTieringConfigurations: [
                {
                    name: "baseIntelligentTieringConfig",
                    archiveAccessTierTime: Duration.days(90),
                    deepArchiveAccessTierTime: Duration.days(180),
                },
            ],
        });

        // Lambda function to process the uploaded doc and Publish and ACK to IoT Core
        const processingLambdaLogGroup = new aws_logs.LogGroup(this, "processing-lambda-log-group", {
            logGroupName: "iot-file-upload/lambda/processDocument",
            retention: aws_logs.RetentionDays.TWO_MONTHS,
            removalPolicy: RemovalPolicy.RETAIN,
            encryptionKey: encryptionKey,
        });
        const processingLambdaLogsPolicyStatement = new aws_iam.PolicyStatement({
            effect: aws_iam.Effect.ALLOW,
            actions: [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            resources: [`${processingLambdaLogGroup.logGroupArn}`]
        });
        const publishAckPolicyStatement = new aws_iam.PolicyStatement({
            effect: aws_iam.Effect.ALLOW,
            actions: ["iot:Publish"],
            resources: [`arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicAckSuffix}/*`]
        });
        const uploadProcessingFunctionRole = new aws_iam.Role(this, "uploadProcessingFunctionRole", {
            assumedBy: new aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            description: 'Role assumed by the Lambda function for processing the Uploaded documents',
            inlinePolicies: {
                uploadProcessingLambdaPolicy: new aws_iam.PolicyDocument({
                    statements: [processingLambdaLogsPolicyStatement, publishAckPolicyStatement],
                })
            }
        });
        const uploadProcessingFunction = new lambda.Function(this, "uploadProcessing", {
            environment: {
                LOG_LEVEL: "DEBUG",
                STORE_BUCKET_NAME: storageBucket.bucketName,
                TOPIC_REQ_KW: topicRequestSuffix,
                TOPIC_ACK_KW: topicAckSuffix
            },
            role: uploadProcessingFunctionRole,
            code: lambda.Code.fromAsset("./function/src/doc_upload_processing"),
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "doc_upload_processing.lambda_handler",
            environmentEncryption: encryptionKey,
            logGroup: processingLambdaLogGroup
        });
        encryptionKey.grantEncryptDecrypt(uploadProcessingFunction);
        stagingBucket.grantReadWrite(uploadProcessingFunction);
        storageBucket.grantReadWrite(uploadProcessingFunction);
        // This Lambda is invoked by a new object created in the Staging bucket
        uploadProcessingFunction.addEventSource(new LambdaEventSource.S3EventSource(stagingBucket, {
            events: [aws_s3.EventType.OBJECT_CREATED]
        }));


        // As a convenience for the users create an IoT Policy and a Thing Group for the Things allowed to Upload
        const uploaderPolicyDocument = {
            Version: "2012-10-17",
            Statement: [
                {
                    Effect: "Allow",
                    Action: ["iot:Connect"],
                    Resource: [
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:client/\${iot:Connection.Thing.ThingName}`,
                    ]
                }, {
                    Effect: "Allow",
                    Action: ["iot:Publish"],
                    Resource: [
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicRequestSuffix}/\${iot:Connection.Thing.ThingName}`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicRequestSuffix}/\${iot:Connection.Thing.ThingName}/*`,
                    ]
                }, {
                    Effect: "Allow",
                    Action: ["iot:Subscribe"],
                    Resource: [
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topicfilter/${topicPrefix}/${topicResponseSuffix}/\${iot:Connection.Thing.ThingName}`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topicfilter/${topicPrefix}/${topicResponseSuffix}/\${iot:Connection.Thing.ThingName}/*`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topicfilter/${topicPrefix}/${topicAckSuffix}/\${iot:Connection.Thing.ThingName}`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topicfilter/${topicPrefix}/${topicAckSuffix}/\${iot:Connection.Thing.ThingName}/*`,
                    ]
                }, {
                    Effect: "Allow",
                    Action: ["iot:Receive"],
                    Resource: [
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicResponseSuffix}/\${iot:Connection.Thing.ThingName}`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicResponseSuffix}/\${iot:Connection.Thing.ThingName}/*`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicAckSuffix}/\${iot:Connection.Thing.ThingName}`,
                        `arn:aws:iot:${Stack.of(this).region}:${Stack.of(this).account}:topic/${topicPrefix}/${topicAckSuffix}/\${iot:Connection.Thing.ThingName}/*`,
                    ]
                }
            ],
        }

        const uploaderPolicy = new aws_iot.CfnPolicy(this, "uploaderPolicy", {
            policyName: "uploaderPolicy",
            policyDocument: uploaderPolicyDocument
        });

        const uploaderThingGroup = new aws_iot.CfnThingGroup(this, "uploaderThingGroup", {
            thingGroupName: "uploaderThingGroup",
            thingGroupProperties: {
                thingGroupDescription: "A Thing Group for the devices that are allowed to upload documents to S3."
            }
        });

        // Unfortunately the code below is not supported by CDK at this time.
        // Manual attachment of the policy to the group is required. Ticket: https://github.com/aws/aws-cdk/issues/26166
        /*
        new aws_iot.CfnPolicyPrincipalAttachment(this, "uploaderPolicyAttachment", {
            policyName: uploaderPolicy.policyName || "",
            principal: uploaderThingGroup.attrArn
        });
         */

        NagSuppressions.addResourceSuppressions(
            [
                uploadResponseFunctionRole,
                iotRoleUploadRequest,
                uploadProcessingFunctionRole,
            ], [
                {
                    id: "AwsSolutions-IAM5",
                    reason: "The policies are restricted by a prefix or generated as prescribed by CDK",
                },
            ],
            true
        );

        // Publish a few outputs as helper for people or other stacks
        new CfnOutput(this, "docUploadStagingBucketNameRef", {
            value: stagingBucket.bucketName,
            description: "The name of the Bucket receiving files uploads",
            exportName: "docUploadStagingBucketNameRef",
        });

        new CfnOutput(this, "docUploadStorageBucketNameRef", {
            value: storageBucket.bucketName,
            description: "The name of the Bucket storing files uploads",
            exportName: "docUploadStorageBucketNameRef",
        });

    }
}
