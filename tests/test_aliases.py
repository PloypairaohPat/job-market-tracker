"""The alias-review helper (src/cleaning/aliases.py).

Every test works on a temp copy of company_aliases.json and temp CSVs with
FAKE names. The repo's own alias file must come out of the run unchanged.
"""

import csv
import hashlib
import json
import shutil

import pytest

from src.cleaning import aliases
from src.cleaning.company_normalizer import ALIASES_PATH

MERGE = ["name_a", "name_b", "relation", "similarity", "approved"]
SPONSOR = ["company_key", "lca_employer_key", "relation", "similarity", "approved"]


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


REAL_DIGEST = digest(ALIASES_PATH)


@pytest.fixture(autouse=True)
def real_file_untouched():
    before = digest(ALIASES_PATH)
    yield
    assert digest(ALIASES_PATH) == before == REAL_DIGEST


@pytest.fixture
def alias_file(tmp_path):
    path = tmp_path / "company_aliases.json"
    shutil.copy(ALIASES_PATH, path)
    return path


def write_csv(path, header, rows):
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def merge_csv(tmp_path, rows, extra=()):
    header = MERGE + list(extra)
    return write_csv(tmp_path / "company_merge_candidates.csv", header, rows)


def run(csv_path, alias_file, write=False, capsys=None):
    result = aliases.apply(csv_path, alias_file, write=write)
    out = capsys.readouterr().out if capsys else ""
    return result, out


def mapped(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["aliases"]


# --------------------------------------------------------------------- #


def test_dry_run_prints_the_plan_and_diff_and_writes_nothing(tmp_path, alias_file, capsys):
    before = alias_file.read_bytes()
    path = merge_csv(
        tmp_path,
        [
            ["fakeco", "fakeco analytics", "containment", "1.0", "y"],
            ["fake bravo", "fake bravo labs", "containment", "1.0", ""],  # not approved
        ],
    )
    result, out = run(path, alias_file, capsys=capsys)
    assert [(k, v) for _, k, v in result.added] == [("fakeco analytics", "fakeco")]
    assert result.n_unapproved == 1
    assert "would add 1 alias(es):" in out and "'fakeco analytics' -> 'fakeco'" in out
    assert '+    "fakeco analytics": "fakeco"' in out  # the JSON diff
    assert "dry run: nothing written" in out
    assert alias_file.read_bytes() == before


def test_write_appends_sorted_and_keeps_meta_comments_order_and_format(
    tmp_path, alias_file, capsys
):
    original = alias_file.read_text(encoding="utf-8")
    path = merge_csv(
        tmp_path,
        [
            ["fake zulu", "fake zulu group", "containment", "1.0", "yes"],
            ["fake alpha", "fake alpha data", "containment", "1.0", "X"],
        ],
    )
    _, out = run(path, alias_file, write=True, capsys=capsys)
    text = alias_file.read_text(encoding="utf-8")
    assert text.startswith(original.rsplit("\n  }\n}", 1)[0])  # every old line kept, in order
    assert text.endswith(
        '"fake alpha data": "fake alpha",\n    "fake zulu group": "fake zulu"\n  }\n}\n'
    )
    data = json.loads(text)
    assert data["_meta"] == json.loads(original)["_meta"]
    assert [k for k in data["aliases"] if k.startswith("_comment")] == [
        k for k in json.loads(original)["aliases"] if k.startswith("_comment")
    ]
    assert "—" in text  # UTF-8 kept, not escaped
    for command in aliases.FOLLOW_UP:
        assert command in out
    assert out.index("apply_cleaning --only companies") < out.index("lca_loader --rekey")


def test_a_second_run_with_the_same_csv_adds_nothing(tmp_path, alias_file, capsys):
    path = merge_csv(tmp_path, [["fakeco", "fakeco analytics", "containment", "1.0", "true"]])
    run(path, alias_file, write=True, capsys=capsys)
    after_first = alias_file.read_bytes()
    result, out = run(path, alias_file, write=True, capsys=capsys)
    assert result.added == [] and len(result.already) == 1
    assert "nothing to write" in out
    assert alias_file.read_bytes() == after_first


@pytest.mark.parametrize("value", ["y", "YES", " x ", "1", "True"])
def test_approved_values(tmp_path, alias_file, value):
    path = merge_csv(tmp_path, [["fakeco", "fakeco analytics", "containment", "1.0", value]])
    assert len(aliases.plan(*_rows(path), mapped(alias_file)).added) == 1


@pytest.mark.parametrize("value", ["", "n", "no", "maybe", "0"])
def test_anything_else_is_not_approved(tmp_path, alias_file, value):
    path = merge_csv(tmp_path, [["fakeco", "fakeco analytics", "containment", "1.0", value]])
    result = aliases.plan(*_rows(path), mapped(alias_file))
    assert result.added == [] and result.n_unapproved == 1


def _rows(path):
    layout, rows = aliases.read_candidates(path)
    return rows, layout


def test_the_sponsor_csv_and_its_keep_columns(tmp_path, alias_file):
    path = write_csv(
        tmp_path / "sponsor_match_candidates.csv",
        SPONSOR + ["keep_company", "keep_lca"],
        [
            ["fakeco", "fakeco analytics", "containment", "1.0", "y", "", "y"],  # keep the LCA key
            ["fake bravo labs", "fake bravo", "containment", "1.0", "y", "", ""],  # default
            ["fake echo", "fake echo two", "fuzzy", "0.9", "y", "y", "y"],  # both: refused
        ],
    )
    rows, layout = _rows(path)
    assert layout == "sponsor match candidates"
    result = aliases.plan(rows, layout, mapped(alias_file))
    assert [(k, v) for _, k, v in result.added] == [
        ("fakeco", "fakeco analytics"),
        ("fake bravo labs", "fake bravo"),
    ]
    assert result.refused[0][3] == "both keep_company and keep_lca are marked: keep one"


def test_keep_a_and_the_default_direction(tmp_path, alias_file):
    path = merge_csv(
        tmp_path,
        [
            ["fake kilo group", "fake kilo", "containment", "1.0", "y", "y", ""],  # keep a
            ["fake lima", "fake mike", "fuzzy", "0.9", "y", "", ""],  # same length: alphabetical
        ],
        extra=["keep_a", "keep_b"],
    )
    result = aliases.plan(*_rows(path), mapped(alias_file))
    assert [(k, v) for _, k, v in result.added] == [
        ("fake kilo", "fake kilo group"),
        ("fake mike", "fake lima"),
    ]
    assert aliases.default_direction("fakeco analytics", "fakeco") == ("fakeco analytics", "fakeco")


@pytest.mark.parametrize(
    "a,b,why",
    [
        ("", "fakeco", "a key is empty"),
        ("FAKECO Inc", "fakeco", "not a normalized key: 'FAKECO Inc' would be 'fakeco'"),
        ("fake co.", "fakeco", "not a normalized key"),
        ("fakeco", "fakeco", "maps a key onto itself"),
        ("_comment_fake", "fakeco", "reserved"),
    ],
)
def test_bad_rows_are_refused_with_the_reason(tmp_path, alias_file, a, b, why):
    path = merge_csv(tmp_path, [[a, b, "fuzzy", "0.9", "y"]])
    result = aliases.plan(*_rows(path), mapped(alias_file))
    assert result.added == [] and why in result.refused[0][3]


def fake_alias_file(tmp_path, entries, indent=2):
    path = tmp_path / "fake_aliases.json"
    data = {"_meta": {"description": "FAKE", "version": 1}, "aliases": entries}
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_conflicts_cycles_and_chains(tmp_path):
    path = fake_alias_file(
        tmp_path,
        {
            "fake taken": "fake owner",  # fake taken is already mapped elsewhere
            "fake circle": "fake circle labs",  # mapping fake circle labs back would loop
            "fake hub": "fake hub group",  # a target that is itself an alias...
            "fake hub group": "fake hub holdings",  # ...resolves to its final key
            "fake spoke": "fake wheel",  # fake wheel has an alias pointing at it
        },
    )
    csv_path = merge_csv(
        tmp_path,
        [
            ["fake taken", "fake other", "fuzzy", "0.9", "y", "", "y"],
            ["fake circle", "fake circle labs", "containment", "1.0", "y", "y", ""],
            ["fake hub", "fake hub data", "containment", "1.0", "y", "y", ""],
            ["fake wheel", "fake wheel works", "containment", "1.0", "y", "", "y"],
        ],
        extra=["keep_a", "keep_b"],
    )
    result = aliases.plan(*_rows(csv_path), mapped(path))
    why = {line: reason for line, _, _, reason in result.refused}
    assert "conflict: 'fake taken' is already mapped to 'fake owner'" in why[2]
    assert "would create a cycle" in why[3]
    assert "would make a chain: 'fake spoke' already map to 'fake wheel'" in why[5]
    # the chained target resolves all the way: no alias ever points at an alias
    assert [(k, v) for _, k, v in result.added] == [("fake hub data", "fake hub holdings")]


def test_rows_see_the_rows_accepted_before_them(tmp_path):
    path = fake_alias_file(tmp_path, {})
    csv_path = merge_csv(
        tmp_path,
        [
            ["fakeco", "fakeco analytics", "containment", "1.0", "y"],
            ["fakeco", "fakeco analytics", "containment", "1.0", "y"],  # duplicate: already
            ["fakeco analytics", "fakeco", "containment", "1.0", "y", "y", ""],  # reversed: cycle
        ],
        extra=["keep_a", "keep_b"],
    )
    result = aliases.plan(*_rows(csv_path), mapped(path))
    assert len(result.added) == 1 and len(result.already) == 1
    assert "would create a cycle" in result.refused[0][3]


def test_the_files_own_indent_is_kept(tmp_path, capsys):
    path = fake_alias_file(tmp_path, {"fake one": "fake"}, indent=4)
    csv_path = merge_csv(tmp_path, [["fake two", "fake two group", "containment", "1.0", "y"]])
    run(csv_path, path, write=True, capsys=capsys)
    text = path.read_text(encoding="utf-8")
    assert '\n        "fake two group": "fake two"\n    }\n}\n' in text


def test_a_csv_that_isnt_a_candidate_file_is_an_error(tmp_path, alias_file, capsys):
    path = write_csv(tmp_path / "other.csv", ["a", "b"], [["x", "y"]])
    assert aliases.main(["apply", "--from", str(path), "--aliases", str(alias_file)]) == 1
    assert "not a candidate CSV" in capsys.readouterr().err


def test_cli_dry_run_then_write(tmp_path, alias_file, capsys):
    path = merge_csv(tmp_path, [["fakeco", "fakeco analytics", "containment", "1.0", "y"]])
    before = alias_file.read_bytes()
    assert aliases.main(["apply", "--from", str(path), "--aliases", str(alias_file)]) == 0
    assert alias_file.read_bytes() == before
    assert (
        aliases.main(["apply", "--from", str(path), "--aliases", str(alias_file), "--write"]) == 0
    )
    assert mapped(alias_file)["fakeco analytics"] == "fakeco"
    capsys.readouterr()
