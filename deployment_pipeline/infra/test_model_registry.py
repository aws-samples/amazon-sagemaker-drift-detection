from datetime import datetime, timedelta

import pytest
from botocore.stub import Stubber

from infra.model_registry import ModelRegistry


def get_package(version: int, creation_time: datetime = datetime.fromtimestamp(0)):
    return {
        "ModelPackageName": "STUB",
        "ModelPackageGroupName": "test-package-group",
        "ModelPackageVersion": version,
        "ModelPackageArn": f"arn:aws:sagemaker:REGION:ACCOUNT:model-package/test-package-group/{version}",
        "CreationTime": creation_time,
        "ModelPackageStatus": "Completed",
        "ModelApprovalStatus": "Approved",
    }


def test_create_model_package_group():
    # Create model registry
    registry = ModelRegistry()

    with Stubber(registry.sm_client) as stubber:
        # Add test package
        expected_params = {
            "ModelPackageGroupDescription": "test package group",
            "ModelPackageGroupName": "test-package-group",
        }
        expected_response = {
            "ModelPackageGroupArn": "arn:aws:sagemaker:REGION:ACCOUNT:model-package-group/test-package-group",
        }
        stubber.add_response(
            "create_model_package_group", expected_response, expected_params
        )

        # Add project tags
        expected_params = {
            "ResourceArn": "arn:aws:sagemaker:REGION:ACCOUNT:model-package-group/test-package-group",
            "Tags": [
                {"Key": "sagemaker:project-name", "Value": "test-project-name"},
                {"Key": "sagemaker:project-id", "Value": "test-project-id"},
            ],
        }
        expected_response = {
            "Tags": [
                {"Key": "sagemaker:project-name", "Value": "test-project-name"},
                {"Key": "sagemaker:project-id", "Value": "test-project-id"},
            ]
        }
        stubber.add_response("add_tags", expected_response)

        # Second time, add the client error if this exists
        expected_params = {
            "ModelPackageGroupDescription": "test package group",
            "ModelPackageGroupName": "test-package-group",
        }
        stubber.add_client_error(
            "create_model_package_group",
            "ValidationException",
            "Model Package Group already exists",
            expected_params=expected_params,
        )

        created = registry.create_model_package_group(
            "test-package-group",
            "test package group",
            "test-project-name",
            "test-project-id",
        )
        assert created is True

        created = registry.create_model_package_group(
            "test-package-group",
            "test package group",
            "test-project-name",
            "test-project-id",
        )
        assert created is False


def test_get_latest_approved_model_packages():
    # Create model registry
    registry = ModelRegistry()

    with Stubber(registry.sm_client) as stubber:
        # Empty list with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
        }
        expected_response = {
            "ModelPackageSummaryList": [],
            "NextToken": "MORE1",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 1 with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "NextToken": "MORE1",
        }
        expected_response = {
            "ModelPackageSummaryList": [get_package(3)],
            "NextToken": "MORE2",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 2 with two more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "NextToken": "MORE2",
        }
        expected_response = {
            "ModelPackageSummaryList": [
                get_package(2),
                get_package(1),
            ],
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)

        response = registry.get_latest_approved_packages(
            model_package_group_name="test-package-group",
            max_results=2,
        )
        # Expect to get two version
        assert len(response) == 2
        assert response == [
            get_package(3),
            get_package(2),
        ]


def test_empty_latest_approved_model_packages():
    # Create model registry
    registry = ModelRegistry()

    with Stubber(registry.sm_client) as stubber:
        # Empty list with no more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
        }
        expected_response = {
            "ModelPackageSummaryList": [],
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)

        # Expect error when no results
        with pytest.raises(Exception):
            registry.get_latest_approved_packages(
                model_package_group_name="test-package-group",
                max_results=2,
            )


def test_get_latest_approved_model_packages_after_creation():
    # Create model registry
    registry = ModelRegistry()
    now = datetime.now()

    with Stubber(registry.sm_client) as stubber:
        # Empty list with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "CreationTimeAfter": now - timedelta(3),
        }
        expected_response = {
            "ModelPackageSummaryList": [],
            "NextToken": "MORE1",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 1 with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "CreationTimeAfter": now - timedelta(3),
            "NextToken": "MORE1",
        }
        expected_response = {
            "ModelPackageSummaryList": [get_package(3, now - timedelta(1))],
            "NextToken": "MORE2",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 2 with two more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "CreationTimeAfter": now - timedelta(3),
            "NextToken": "MORE2",
        }
        expected_response = {
            "ModelPackageSummaryList": [
                get_package(2, now - timedelta(2)),
                get_package(1, now - timedelta(3)),
            ],
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)

        response = registry.get_latest_approved_packages(
            model_package_group_name="test-package-group",
            max_results=2,
            creation_time_after=now - timedelta(3),
        )
        # Expect to get two version
        assert len(response) == 2
        assert response == [
            get_package(3, now - timedelta(1)),
            get_package(2, now - timedelta(2)),
        ]


def test_empty_latest_approved_model_packages_after_creation():
    # Create model registry
    registry = ModelRegistry()
    now = datetime.now()

    with Stubber(registry.sm_client) as stubber:
        # Empty list with no more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 2,
            "CreationTimeAfter": now - timedelta(3),
        }
        expected_response = {
            "ModelPackageSummaryList": [],
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)

        # Expect no error, but empty list for creation time after
        response = registry.get_latest_approved_packages(
            model_package_group_name="test-package-group",
            max_results=2,
            creation_time_after=now - timedelta(3),
        )
        assert len(response) == 0


def test_get_versioned_approved_model_packages():
    # Create model registry
    registry = ModelRegistry()

    with Stubber(registry.sm_client) as stubber:
        # Empty list with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 100,
        }
        expected_response = {
            "ModelPackageSummaryList": [],
            "NextToken": "MORE1",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 1 with more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 100,
            "NextToken": "MORE1",
        }
        expected_response = {
            "ModelPackageSummaryList": [get_package(3)],
            "NextToken": "MORE2",
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)
        # Version 2 with two more
        expected_params = {
            "ModelPackageGroupName": "test-package-group",
            "ModelApprovalStatus": "Approved",
            "SortBy": "CreationTime",
            "MaxResults": 100,
            "NextToken": "MORE2",
        }
        expected_response = {
            "ModelPackageSummaryList": [
                get_package(2),
                get_package(1),
            ],
        }
        stubber.add_response("list_model_packages", expected_response, expected_params)

        # Get model versions
        response = registry.get_versioned_approved_packages(
            model_package_group_name="test-package-group",
            model_package_versions=[1, 2],
        )
        # Expect to get two version
        assert len(response) == 2
        assert response == [
            get_package(1),
            get_package(2),
        ]


def test_filter_package_version():
    """
    Select the sorted package versions.  Validate we return in the order we ask for.
    """
    unsorted_packages = [
        get_package(1),
        get_package(3),
        get_package(2),
    ]

    registry = ModelRegistry()
    versions = [2, 3, 2]
    response = registry.select_versioned_packages(unsorted_packages, versions)
    assert len(response) == 3
    assert response == [
        get_package(2),
        get_package(3),
        get_package(2),
    ]


def test_get_pipeline_execution_arn():
    # TODO: Implement
    pass


def test_get_processing_output():
    # TODO: Implement
    pass
