import os

from adpulse import config


def test_dotenv_parsing_handles_comments_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment line\n"
        "ADPULSE_TEST_A=local                 # inline comment\n"
        "ADPULSE_TEST_B=\n"
        "ADPULSE_TEST_C=   # only a comment\n"
        "ADPULSE_TEST_D=\"has # hash\"\n"
        "ADPULSE_TEST_E=act_1,act_2\n"
    )
    for k in "ABCDE":
        monkeypatch.delenv(f"ADPULSE_TEST_{k}", raising=False)
    config._load_dotenv(env)
    assert os.environ["ADPULSE_TEST_A"] == "local"
    assert os.environ["ADPULSE_TEST_B"] == ""
    assert os.environ["ADPULSE_TEST_C"] == ""
    assert os.environ["ADPULSE_TEST_D"] == "has # hash"
    assert os.environ["ADPULSE_TEST_E"] == "act_1,act_2"


def test_default_window_is_lookback_days_ending_yesterday():
    s = config.Settings(lookback_days=30)
    start, end = s.default_window()
    assert (s.today() - end).days == 1
    assert (end - start).days == 29
