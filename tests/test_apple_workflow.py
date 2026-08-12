from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "apple-ci.yml"


def test_xcode_projects_run_tests_when_enabled():
    workflow = WORKFLOW.read_text()

    assert "xcodebuild test" in workflow
    assert "inputs.run-tests" in workflow
    assert "-resultBundlePath" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_apple_build_data_is_job_scoped_and_cleaned():
    workflow = WORKFLOW.read_text()

    assert "${{ runner.temp }}" not in workflow
    assert 'DERIVED_DATA_PATH=$RUNNER_TEMP/oakfarm-derived-data/' in workflow
    assert 'RESULT_BUNDLE_PATH=$RUNNER_TEMP/oakfarm-test-results/' in workflow
    assert '"$RUNNER_TEMP"/oakfarm-derived-data/*' in workflow
    assert 'rm -rf "$DERIVED_DATA_PATH"' in workflow
