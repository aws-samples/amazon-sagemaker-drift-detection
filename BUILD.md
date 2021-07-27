# Amazon SageMaker Drift Detection Pipeline

This page has details on how to build a custom SageMaker MLOps template from source.

To build from source:

1. Open a [System Terminal](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-launcher.html) in Amazon SageMaker Studio
2. Clone this repository

```
git clone https://github.com/aws-samples/amazon-sagemaker-drift-detection
cd amazon-sagemaker-drift-detection.git
```

## Prerequisites

This project uses the AWS Cloud Development Kit [CDK](https://aws.amazon.com/cdk/).  To [get started](https://docs.aws.amazon.com/cdk/latest/guide/getting_started.html) with AWS CDK you need [Node.js](https://nodejs.org/en/download/) 10.13.0 or later.

### Install the AWS CDK

Install the AWS CDK Toolkit globally using the following Node Package Manager command.

```
npm install -g aws-cdk
```

Run the following command to verify correct installation and print the version number of the AWS CDK.

```
cdk --version
```

### Setup Python Environment for CDK

This project uses AWS CDK with python bindings to deploy resources to your AWS account.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

This project is set up like a standard Python project.  The initialization
process also creates a virtualenv within this project, stored under the `.venv`
directory.  To create the virtualenv it assumes that there is a `python3`
(or `python` for Windows) executable in your path with access to the `venv`
package. If for any reason the automatic creation of the virtualenv fails,
you can create the virtualenv manually.

To manually create a virtualenv on MacOS and Linux:

```
python3.8 -m venv .venv
```

After the init process completes and the virtualenv is created, you can use the following
step to activate your virtualenv.

```
source .venv/bin/activate
```

If you are a Windows platform, you would activate the virtualenv like this:

```
.venv\Scripts\activate.bat
```

Once the virtualenv is activated, you can install the required dependencies.

```
pip install -r requirements.txt
```

### Add Permissions for CDK

AWS CDK requires permissions to create AWS CloudFormation Stacks and the associated resources for your current execution role. If you have cloned this repository into SageMaker Studio, you will need to add an inline policy to your SageMaker Studio execution role. You can find your user's role ARN by browsing to the Studio dashboard.

![Studio Execution Role](docs/studio-execution-role.png)

The following commands will add the CDK-DeployPolicy to this  execution role. Before running them, substitute the role ARN. Alternatively you can follow the steps below using the AWS console.

Browse to the [IAM](https://console.aws.amazon.com/iam) section in the console, and find this role.

Then, click the **Add inline policy** link, switch to to the **JSON** tab, and paste the following inline policy:

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "s3:*"
            ],
            "Effect": "Allow",
            "Resource": [
                "arn:aws:s3:::cdktoolkit-*",
                "arn:aws:s3:::sagemaker-project-*"
            ]
        },
        {
            "Action": [
                "lambda:*"
            ],
            "Effect": "Allow",
            "Resource": [
              "arn:aws:lambda:*:*:function:drift-*"
            ]
        },
        {
            "Action": [
                "cloudformation:*",
                "servicecatalog:*",
                "events:*"
            ],
            "Effect": "Allow",
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:DeleteRole"
            ],
            "Resource": "arn:aws:iam::*:role/drift-*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "iam:GetRole",
                "iam:PassRole",
                "iam:GetRolePolicy",
                "iam:AttachRolePolicy",
                "iam:PutRolePolicy",
                "iam:DetachRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:CreateServiceLinkedRole"
            ],
            "Resource": [
              "arn:aws:iam::*:role/drift-*",
              "arn:aws:iam::*:role/service-role/AmazonSageMaker*"
            ]
        }
    ]
}
```

Click **Review policy** and provide the name `CDK-DeployPolicy` then click **Create policy**

### Bootstrap the CDK

If this is the first time you have run the CDK, you may need to [Bootstrap](https://docs.aws.amazon.com/cdk/latest/guide/bootstrapping.html) your account.  If you have multiple deployment targets see also [Specifying up your environment](https://docs.aws.amazon.com/cdk/latest/guide/cli.html#cli-environment) in the CDK documentation.

```
cdk bootstrap
```

You should now be able to list the stacks by running:

```
cdk list
```

Which will return the following stacks:

* `drift-service-catalog`
* `drift-pipeline`

## Publish the MLOps Template

In this section you will publish the MLOPs Project template to the **AWS Service Catalog**.

### Deploy the SageMaker MLOps Project template

Run the following command to deploy the MLOps project template, passing the required `ExecutionRoleArn` parameter.  You can copy this from your SageMaker Studio dashboard as show above.

```
export EXECUTION_ROLE_ARN=<<sagemaker-studio-execution-role>>
cdk deploy drift-service-catalog \
    --parameters ExecutionRoleArn=$EXECUTION_ROLE_ARN \
    --parameters PortfolioName="SageMaker Organization Templates" \
    --parameters PortfolioOwner="administrator" \
    --parameters ProductVersion=1.0
```

You will be presented with the list of changes, and asked to confirm to deploy these changes.

`NOTE`: If you are seeing errors running the above command ensure you have [Enabled SageMaker project templates for Studio users](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-projects-studio-updates.html) to grant access to these resources in Amazon S3.

## Create the MLOps Project

Now you can return to the [README.md](README.md#creating-a-new-project-in-amazon-sagemaker-studio) to Creating a new Project in Amazon SageMaker Studio

### Create project with CDK

Alternatively you can run the following command to create the drift pipeline for an existing project:

```
export SAGEMAKER_PROJECT_NAME=<<existing-project-name>>
export SAGEMAKER_PROJECT_ID=<<existing-project-id>>
cdk deploy drift-pipeline -c drift:ProductsUseRoleName="" \
    --parameters SageMakerProjectName=$SAGEMAKER_PROJECT_NAME \
    --parameters SageMakerProjectId=$SAGEMAKER_PROJECT_ID
```