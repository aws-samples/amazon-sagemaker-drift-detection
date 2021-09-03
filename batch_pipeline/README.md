
# Amazon SageMaker Drift Detection

This folder contains the code to create a batch pipeline that includes a SageMaker Transform Job and [Model Monitor](https://aws.amazon.com/sagemaker/model-monitor/) Processing Job.

## Build Pipeline

The model build pipeline contains three stages:
1. Source: This stage pulls the latest code from the **AWS CodeCommit** repository.
2. Build: The **AWS CodeBuild** action creates an Amazon SageMaker Pipeline definition and stores this definition as a JSON on S3. Take a look at the pipeline definition in the CodeCommit repository `pipelines/pipeline.py`. The build also creates an **AWS CloudFormation** template using the AWS CDK - take a look at the respective CDK App `app.py`.
3. BatchStaging: This stage executes the staging CloudFormation template to create/update a **SageMaker Pipeline** based on the latest approved model. The pipeline includes a manual approval gate, which triggers the deployment of the model to production.
4. BatchProd: This stage creates or updates a **SageMaker Pipelines** which includes a **SageMaker Model Monitor** job that will output `constraint_violations.json` when drift is detected.  A [CloudWatch Event](https://docs.aws.amazon.com/codepipeline/latest/userguide/create-cloudtrail-S3-source-cfn.html) rule is setup to trigger re-training when this this file is output to S3.

![Build Pipeline](../docs/drift-batch-pipeline.png)

The batch transform pipeline will be triggered when a new file is uploaded to S3 or on a regular schedule.