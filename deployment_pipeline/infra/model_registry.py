import logging
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Class for managing models in the registry.
    """

    def __init__(self):
        config = Config(retries={"max_attempts": 10, "mode": "standard"})
        self.sm_client = boto3.client("sagemaker", config=config)

    def create_model_package_group(
        self,
        model_package_group_name: str,
        description: str,
        project_name: str,
        project_id: str,
    ):
        """
        Create the model package group if it doesn't exist.
        """
        try:
            response = self.sm_client.create_model_package_group(
                ModelPackageGroupName=model_package_group_name,
                ModelPackageGroupDescription=description,
            )
            model_package_group_arn = response["ModelPackageGroupArn"]
            # Add tags separately
            self.sm_client.add_tags(
                ResourceArn=model_package_group_arn,
                Tags=[
                    {"Key": "sagemaker:project-name", "Value": project_name},
                    {"Key": "sagemaker:project-id", "Value": project_id},
                ],
            )
            logger.info(f"Model package group {model_package_group_arn} created")
            return True

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            if (
                error_code == "ValidationException"
                and "Model Package Group already exists" in error_message
            ):
                logger.info(
                    f"Model package group {model_package_group_name} already exists"
                )
                return False
            else:
                logger.error(error_message)
                raise Exception(error_message)

    def get_latest_approved_packages(
        self,
        model_package_group_name: str,
        max_results: int,
        creation_time_after: datetime = None,
    ) -> list:
        """Gets the latest approved model packages for a model package group.

        Args:
            model_package_group_name: The model package group name.
            max_results: The maximum number of model packages to return.
            creation_time_after: Optional filter that returns only model
            packages created after the specified time (datetime).

        Returns:
            The list of model packages, sorted by most recently created
        """
        try:
            # Get the latest approved model package
            args = {
                "ModelPackageGroupName": model_package_group_name,
                "ModelApprovalStatus": "Approved",
                "SortBy": "CreationTime",
                "MaxResults": max_results,
            }
            # Add optional creation time after
            if creation_time_after is not None:
                args = {**args, "CreationTimeAfter": creation_time_after}
            response = self.sm_client.list_model_packages(**args)
            model_packages = response["ModelPackageSummaryList"]

            # Fetch more packages if none returned with continuation token
            while len(model_packages) < max_results and "NextToken" in response:
                logger.debug(
                    "Getting more packages for token: {}".format(response["NextToken"])
                )
                # Set the NextToken to override any previous token
                args = {**args, "NextToken": response["NextToken"]}
                response = self.sm_client.list_model_packages(**args)
                model_packages.extend(response["ModelPackageSummaryList"])

            # Return error if no packages found
            if len(model_packages) == 0 and creation_time_after is None:
                error_message = (
                    f"No approved packages found for: {model_package_group_name}"
                )
                logger.error(error_message)
                raise Exception(error_message)

            # Return as a list of model packages limited by max results
            return model_packages[:max_results]

        except ClientError as e:
            error_message = e.response["Error"]["Message"]
            logger.error(error_message)
            raise Exception(error_message)

    def get_versioned_approved_packages(
        self,
        model_package_group_name: str,
        model_package_versions: list,
    ) -> list:
        """Gets specific versions of approved model packages for a model package group.

        Args:
            model_package_group_name: The model package group name.
            model_package_versions: The model package versions to return.
            creation_time_after: Optional filter that returns only model
            packages created after the specified time (timestamp).

        Returns:
            The list of model packages, sorted by most recently created
        """
        max_results = 100
        unique_versions = set(model_package_versions)

        try:
            # Get the approved model package until
            args = {
                "ModelPackageGroupName": model_package_group_name,
                "ModelApprovalStatus": "Approved",
                "SortBy": "CreationTime",
                "MaxResults": max_results,
            }
            response = self.sm_client.list_model_packages(**args)
            model_packages = self.select_versioned_packages(
                response["ModelPackageSummaryList"], unique_versions
            )

            # Fetch more packages if none returned with continuation token
            while (
                len(model_packages) < len(unique_versions) and "NextToken" in response
            ):
                logger.debug(
                    "Getting more packages for token: {}".format(response["NextToken"])
                )
                args = {**args, "NextToken": response["NextToken"]}
                response = self.sm_client.list_model_packages(**args)
                model_packages.extend(
                    self.select_versioned_packages(
                        response["ModelPackageSummaryList"], unique_versions
                    )
                )

            # Return error if no packages found
            if len(model_packages) == 0:
                error_message = (
                    f"No approved packages found for: {model_package_group_name} "
                    f"and versions: {model_package_versions}"
                )
                logger.error(error_message)
                raise Exception(error_message)

            # Return as a list of model package group in order of versions
            return self.select_versioned_packages(
                model_packages, model_package_versions
            )

        except ClientError as e:
            error_message = e.response["Error"]["Message"]
            logger.error(error_message)
            raise Exception(error_message)

    def select_versioned_packages(
        self, model_packages: list, model_package_versions: list
    ):
        """Filters the model packages based on a list of model package versions.

        Args:
            model_packages: The list of packages.
            model_package_versions: The list of versions.

        Returns:
            The Filtered list of model packages in order of versions specified.
            Duplicate versions will be preserved.
        """

        filtered_packages = []
        for version in model_package_versions:
            filtered_packages += [
                p for p in model_packages if p["ModelPackageVersion"] == version
            ]
        return filtered_packages

    def get_data_check_baseline_uri(self, model_package_arn: str):
        try:
            model_details = self.sm_client.describe_model_package(
                ModelPackageName=model_package_arn
            )
            logger.info(model_details)
            baseline_uri = model_details["DriftCheckBaselines"]["ModelDataQuality"][
                "Constraints"
            ]["S3Uri"]
            # returning the folder containing constraints and statistics
            baseline_uri = baseline_uri.replace("/constraints.json", "")
            return baseline_uri
        except ClientError as e:
            error_message = e.response["Error"]["Message"]
            logger.error(error_message)
            raise Exception(error_message)
