from aws_cdk import core as cdk

from infra.clean_template import remove_policy


def generate_template(
    stack: cdk.Stack, stack_name: str, strip_policies: bool = False
) -> str:
    """Create a CFN template from a stack

    Args:
        stack (cdk.Stack): cdk Stack to synthesize into a CFN template
        stack_name (str): Name to assign to the stack
        strip_policies (bool): remove all policies from the stack. useful for stack containing CodePipeline deployment

    Returns:
        [str]: path of the CFN template
    """

    stage = cdk.Stage(cdk.App(), "IntermediateStage")
    stack(stage, stack_name, synthesizer=cdk.BootstraplessSynthesizer())
    assembly = stage.synth(force=True)
    template_full_path = assembly.stacks[0].template_full_path
    if strip_policies:
        remove_policy(template_full_path, template_full_path)
    return template_full_path
