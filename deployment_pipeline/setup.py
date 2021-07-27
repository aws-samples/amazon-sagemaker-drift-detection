import setuptools


with open("README.md") as fp:
    long_description = fp.read()


setuptools.setup(
    name="amazon_sagemaker_drift_detection_deploy_pipeline",
    version="0.0.1",
    description="Amazon SageMaker Drift Detection Deploy pipeline",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="amazon",
    package_dir={"": "infra"},
    packages=setuptools.find_packages(where="infra"),
    install_requires=[
        "boto3==1.17.83",
        "aws-cdk.core==1.106.1",
        "aws-cdk.aws-iam==1.106.1",
        "aws-cdk.aws-sagemaker==1.106.1",
        "aws-cdk.aws-applicationautoscaling==1.106.1",
        "aws-cdk.aws-cloudwatch==1.106.1",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Utilities",
        "Typing :: Typed",
    ],
)
