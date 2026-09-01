import pytest

from mba_mcp import ats


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://boards.greenhouse.io/acmeco", ("greenhouse", "acmeco")),
        ("https://job-boards.greenhouse.io/acmeco/jobs/4012345", ("greenhouse", "acmeco")),
        ("https://boards-api.greenhouse.io/v1/boards/acmeco/jobs", ("greenhouse", "acmeco")),
        ("https://boards.greenhouse.io/embed/job_board?for=acmeco", ("greenhouse", "acmeco")),
        ("boards.greenhouse.io/acmeco/", ("greenhouse", "acmeco")),
        ("https://jobs.lever.co/leverco", ("lever", "leverco")),
        ("https://jobs.lever.co/leverco/8e1a1b2c", ("lever", "leverco")),
        ("https://api.lever.co/v0/postings/leverco?mode=json", ("lever", "leverco")),
        ("https://jobs.ashbyhq.com/ashbyco", ("ashby", "ashbyco")),
        ("https://jobs.ashbyhq.com/ashbyco/1a2b3c", ("ashby", "ashbyco")),
        ("https://api.ashbyhq.com/posting-api/job-board/ashbyco", ("ashby", "ashbyco")),
        ("https://acme.wd1.myworkdayjobs.com/Careers", ("workday", "acme|wd1|Careers")),
        ("https://citi.wd5.myworkdayjobs.com/en-US/2", ("workday", "citi|wd5|2")),
        (
            "https://moelis.wd1.myworkdayjobs.com/en-US/Experienced-Hires/job/London/Assoc_REQ1",
            ("workday", "moelis|wd1|Experienced-Hires"),
        ),
        (
            "https://blackstone.wd1.myworkdayjobs.com/wday/cxs/blackstone/Blackstone_Careers/jobs",
            ("workday", "blackstone|wd1|Blackstone_Careers"),
        ),
        ("https://jobs.smartrecruiters.com/BoschGroup", ("smartrecruiters", "BoschGroup")),
        (
            "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings",
            ("smartrecruiters", "BoschGroup"),
        ),
    ],
)
def test_detect_ats_recognises_board_urls(url, expected):
    assert ats.detect_ats(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://www.mckinsey.com/careers/search-jobs",
        "https://acme.myworkdayjobs.com/Careers",
        "https://boards.greenhouse.io/",
        "https://boards.greenhouse.io/embed/job_board",
    ],
)
def test_detect_ats_returns_none_for_unknown_boards(url):
    assert ats.detect_ats(url) is None


def test_board_url_per_vendor():
    assert ats.board_url("greenhouse", "acmeco").endswith("/boards/acmeco/jobs")
    assert "postings/leverco" in ats.board_url("lever", "leverco")
    assert ats.board_url("ashby", "ashbyco").endswith("job-board/ashbyco")
    with pytest.raises(ats.AtsError):
        ats.board_url("workday", "acme")


def test_parse_greenhouse(fixture_json):
    jobs = ats.parse_greenhouse(fixture_json("greenhouse.json"), "Acme Co")
    assert len(jobs) == 2  # the posting with no url is dropped
    first = jobs[0]
    assert first == {
        "company": "Acme Co",
        "title": "Summer Associate (MBA) - Strategy",
        "location": "New York, NY",
        "url": "https://boards.greenhouse.io/acmeco/jobs/4012345",
        "posted_at": "2026-07-28",  # first_published wins over updated_at
        "source": "greenhouse",
    }
    assert jobs[1]["posted_at"] == "2026-06-11"


def test_parse_lever_converts_epoch_millis(fixture_json):
    jobs = ats.parse_lever(fixture_json("lever.json"), "Lever Co")
    assert [job["title"] for job in jobs] == ["MBA Summer Associate", "Senior Engineer"]
    assert jobs[0]["url"] == "https://jobs.lever.co/leverco/8e1a1b2c"
    assert jobs[0]["location"] == "Boston, MA"
    assert jobs[0]["posted_at"] == "2025-07-28"
    assert jobs[0]["source"] == "lever"


def test_parse_ashby_skips_unlisted(fixture_json):
    jobs = ats.parse_ashby(fixture_json("ashby.json"), "Ashby Co")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "MBA Intern, Corporate Strategy"
    assert jobs[0]["posted_at"] == "2026-08-10"


def test_parse_adzuna_strips_markup(fixture_json):
    jobs = ats.parse_adzuna(fixture_json("adzuna.json"))
    assert jobs[0]["title"] == "Summer Associate"
    assert jobs[0]["company"] == "Boutique Advisory LLP"
    assert jobs[0]["posted_at"] == "2026-08-05"
    assert jobs[0]["source"] == "adzuna"


def test_parsers_tolerate_junk_payloads():
    for parser in (ats.parse_greenhouse, ats.parse_lever, ats.parse_ashby):
        assert parser({}, "X") == []
        assert parser([], "X") == []
        assert parser({"jobs": None}, "X") == []
        assert parser(["not a dict"], "X") == []


def test_matches_filters_on_keywords_and_location(fixture_json):
    jobs = ats.parse_greenhouse(fixture_json("greenhouse.json"), "Acme Co")
    summer = [job for job in jobs if ats.matches(job, "summer associate", None)]
    assert [job["title"] for job in summer] == ["Summer Associate (MBA) - Strategy"]
    london = [job for job in jobs if ats.matches(job, None, "london")]
    assert [job["title"] for job in london] == ["Data Analyst"]
    assert [job for job in jobs if ats.matches(job, "summer", "london")] == []


def test_fetch_board_uses_injected_client(fixture_json, monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/acmeco/jobs"
        return httpx.Response(200, json=fixture_json("greenhouse.json"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = ats.fetch_board("greenhouse", "acmeco", "Acme Co", client=client)
    assert len(jobs) == 2


def test_fetch_board_wraps_http_errors():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ats.AtsError, match="404"):
            ats.fetch_board("lever", "nope", "Nope", client=client)


# --------------------------------------------------------------------------
# Workday, SmartRecruiters and careers-page discovery
# --------------------------------------------------------------------------


def test_split_workday_slug():
    assert ats.split_workday_slug("citi|wd5|2") == ("citi", "wd5", "2")
    with pytest.raises(ats.AtsError, match="Malformed"):
        ats.split_workday_slug("citi|wd5")


def test_parse_workday_builds_job_urls_and_dates(fixture_json):
    from datetime import date

    jobs = ats.parse_workday(
        fixture_json("workday.json"), "PJT Partners", "pjtpartners|wd1|Careers",
        today=date(2026, 9, 1),
    )
    assert len(jobs) == 3  # the posting with no externalPath is dropped
    assert jobs[0]["url"] == (
        "https://pjtpartners.wd1.myworkdayjobs.com/Careers"
        "/job/London/Associate---Strategic-Advisory--Industrials-_R0003380"
    )
    assert jobs[0]["posted_at"] == "2026-08-29"  # "Posted 3 Days Ago"
    assert jobs[1]["posted_at"] == "2026-09-01"  # "Posted Today"
    assert jobs[2]["posted_at"] == "2026-08-02"  # "Posted 30+ Days Ago", approximate
    assert jobs[0]["source"] == "workday"


def test_parse_smartrecruiters(fixture_json):
    jobs = ats.parse_smartrecruiters(fixture_json("smartrecruiters.json"), "Acme Group")
    assert len(jobs) == 2
    assert jobs[0]["url"] == "https://jobs.smartrecruiters.com/AcmeGroup/744000146555579"
    assert jobs[0]["location"] == "New York, NY, United States"
    assert jobs[0]["posted_at"] == "2026-08-20"
    assert jobs[1]["location"] == "Leeds, ENG"  # falls back to city/region


def test_find_board_in_html(fixtures_dir):
    html = (fixtures_dir / "careers_page.html").read_text()
    assert ats.find_board_in_html(html) == ("workday", "acmeadvisory|wd1|Acme_Careers")
    assert ats.find_board_in_html("<html>no board here</html>") is None
    assert ats.find_board_in_html(
        '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acmeco">'
    ) == ("greenhouse", "acmeco")


def test_discover_ats_reads_a_careers_page(fixtures_dir):
    import httpx

    html = (fixtures_dir / "careers_page.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert ats.discover_ats("https://acmeadvisory.com/careers", client=client) == (
            "workday",
            "acmeadvisory|wd1|Acme_Careers",
        )


def test_discover_ats_short_circuits_on_a_board_url():
    # No client passed: if it tried to fetch, it would hit the network.
    assert ats.discover_ats("https://jobs.lever.co/acmeco") == ("lever", "acmeco")


def test_discover_ats_is_quiet_when_a_page_blocks_us():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert ats.discover_ats("https://www.bain.com/careers/", client=client) is None


def test_fetch_workday_pages_and_pushes_keywords_down(fixture_json):
    import httpx

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json=fixture_json("workday.json"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = ats.fetch_board(
            "workday", "pjtpartners|wd1|Careers", "PJT Partners",
            keywords="associate", client=client,
        )
    assert len(seen) == 1  # a short page means no second request
    assert seen[0]["searchText"] == "associate"
    assert len(jobs) == 3


def test_fetch_smartrecruiters_sends_the_query(fixture_json):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "associate"
        assert request.url.path.endswith("/companies/AcmeGroup/postings")
        return httpx.Response(200, json=fixture_json("smartrecruiters.json"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = ats.fetch_board(
            "smartrecruiters", "AcmeGroup", "Acme Group", keywords="associate", client=client
        )
    assert len(jobs) == 2
