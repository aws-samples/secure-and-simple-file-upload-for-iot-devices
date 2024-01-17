#!/usr/bin/env node
import 'source-map-support/register';
import  {App, Aspects, Tags }  from 'aws-cdk-lib';
import { AppStack } from '../lib/app-stack';
import { AwsSolutionsChecks } from "cdk-nag";

const app = new App();
const topStack = new AppStack(app, 'S3FileUploadForIoT', {
  /* If you don't specify 'env', this stack will be environment-agnostic.
   * Account/Region-dependent features and context lookups will not work,
   * but a single synthesized template can be deployed anywhere. */

  /* Uncomment the next line to specialize this stack for the AWS Account
   * and Region that are implied by the current CLI configuration. */
  // env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },

  /* Uncomment the next line if you know exactly what Account and Region you
   * want to deploy the stack to. */
  // env: { account: '123456789012', region: 'us-east-1' },

  /* For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html */
});

// Create an application in AWS Service Catalog
Tags.of(topStack).add("APPLICATION", "S3 File Upload for IoT Device")
// Use cdk-nag to inspect the stack for common problems
Aspects.of(app).add(new AwsSolutionsChecks( {verbose: true} ));