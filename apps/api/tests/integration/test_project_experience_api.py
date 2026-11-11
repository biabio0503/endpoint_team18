import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


CASES = ['sources_confirm_correction_and_job_snapshot_reuse', 'corrected_skill_matches_user_statement_not_original_quote',
         'eligibility_no_documents_and_partial_confirmation', 'delete_reextract_invalidates_answers_and_older_evidence',
         'owner_scope_and_revision_race', 'invalid_model_document_and_cross_document_quote',
         'partial_failure_rate_limit_and_retry_only_missing_document',
         'explicit_no_experience_and_invalidation_when_documents_change',
         'partial_job_cache_and_failed_refresh_preserve_verified_result',
         'classbridge_details_context_and_nonfatal_adjustments',
         'refresh_reuses_extraction_and_never_reassigns_answers',
         'version_upgrade_and_failed_refresh_preserve_answer_boundaries',
         'incident_fixed_model_candidates_are_persisted_and_reused',
         'negation_fixed_candidates_are_persisted_and_reused',
         'negation_version_upgrade_applies_on_explicit_refresh',
         'clause_regressions_remain_unconfirmed_in_comparison_and_roadmap',
         'activity_basis_tracks_effective_project_and_job_evidence']


@pytest.mark.parametrize('case', CASES)
def test_sqlite_project_experience_api(case):
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'experience.db'),
                   ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
                   ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000')
        script = Path(__file__).with_name('project_experience_scenario.py')
        result = subprocess.run([sys.executable, str(script), 'ProjectExperienceAPI.test_' + case],
                                env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
