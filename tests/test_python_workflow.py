from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-ci.yml"


def test_optional_install_command_does_not_render_an_empty_shell_branch():
    workflow = WORKFLOW.read_text()

    assert "INSTALL_COMMAND: ${{ inputs.install-command }}" in workflow
    assert 'bash -lc "$INSTALL_COMMAND"' in workflow
