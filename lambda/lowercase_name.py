import cfnresponse


def lambda_handler(event, context):
    output = event["ResourceProperties"].get("InputString", "").lower()
    responseData = {"OutputString": output}
    cfnresponse.send(event, context, cfnresponse.SUCCESS, responseData)
