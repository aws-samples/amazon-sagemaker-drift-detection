import json
import logging
import os

# Get environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure logging
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)


def remove_policy(input_path: str, output_path: str):
    """Remove all IAM policies from a CloudFormation json template

    CDK implementation of CodePipelines does not respect the CF option to leave a role blank
    to automatically default to the execution role.

    for reference, check https://github.com/aws/aws-cdk/issues/14887
    """
    with open(input_path, "r") as f:
        t = json.load(f)

    # Remove policies
    policy_list = [
        k for k in t["Resources"] if t["Resources"][k]["Type"] == "AWS::IAM::Policy"
    ]
    for p in policy_list:
        logger.debug(f"Removing Policy {p}")
        del t["Resources"][p]

    # Remove policy dependencies
    depends_on = [k for k in t["Resources"] if "DependsOn" in t["Resources"][k]]
    for d in depends_on:
        for p in policy_list:
            if p in t["Resources"][d]["DependsOn"]:
                logger.debug(f"Removing DependsOn {p}")
                t["Resources"][d]["DependsOn"].remove(p)
        if len(t["Resources"][d]["DependsOn"]) == 0:
            del t["Resources"][d]["DependsOn"]

    # Save file back
    logger.info(f"Writing template to: {output_path}")
    with open(output_path, "w") as f:
        json.dump(t, f, indent=2)


if __name__ == "__main__":
    remove_policy(
        "cdk.out/drift-pipeline.template.json",
        "cdk.out/drift-pipeline-clean.template.json",
    )
