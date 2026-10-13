"""Fertiliser planner: the arithmetic is verified independently of the code that produces it."""

import pytest

import fertilizer_engine as engine


def delivered(plan):
    """Nutrients (kg) actually carried by the product totals for the whole area."""
    totals = {"N": 0.0, "P2O5": 0.0, "K2O": 0.0}
    for item in plan["products"]:
        for nutrient in totals:
            totals[nutrient] += item["kg_for_area"] * item["grade"][nutrient] / 100
    return totals


def applied(plan):
    """Nutrients (kg) carried by the individual applications (the schedule)."""
    totals = {"N": 0.0, "P2O5": 0.0, "K2O": 0.0}
    grade = {key: value for key, value in engine.DATA["products"].items()}
    for step in plan["applications"]:
        for item in step["items"]:
            for nutrient in totals:
                totals[nutrient] += item["kg"] * grade[item["key"]][nutrient] / 100
    return totals


@pytest.mark.parametrize("p_source", ["dap", "ssp"])
@pytest.mark.parametrize("k_source", ["mop", "sop"])
@pytest.mark.parametrize("splits", [1, 2, 3, 4])
@pytest.mark.parametrize("dose", [(100, 50, 50), (120, 60, 40), (50, 25, 25), (80, 0, 40), (0, 60, 0)])
def test_products_deliver_exactly_the_requested_dose(dose, splits, p_source, k_source):
    n, p, k = dose
    plan = engine.build_plan(n=n, p2o5=p, k2o=k, area_value=2.5, area_unit="acre", p_source=p_source, k_source=k_source, n_splits=splits)
    ha = plan["area"]["hectares"]
    for got in (delivered(plan), applied(plan)):
        # Rounding to 0.1 kg per product limits the error; DAP N overshoot is a warning case, not a mismatch.
        assert got["P2O5"] == pytest.approx(p * ha, abs=0.25)
        assert got["K2O"] == pytest.approx(k * ha, abs=0.25)
        if plan["warnings"] and "supplies about" in " ".join(plan["warnings"]):
            assert got["N"] > n * ha
        else:
            assert got["N"] == pytest.approx(n * ha, abs=0.3)


def test_dap_nitrogen_is_netted_out_of_urea():
    plan = engine.build_plan(n=100, p2o5=46, k2o=0, area_value=1, area_unit="hectare", p_source="dap", n_splits=2)
    # 46 kg P2O5 needs 100 kg DAP, which carries 18 kg N; urea must supply the other 82 kg N = 178.3 kg.
    by_key = {item["key"]: item for item in plan["products"]}
    assert by_key["dap"]["kg_per_hectare"] == 100.0
    assert by_key["urea"]["kg_per_hectare"] == pytest.approx(82 / 0.46, abs=0.1)
    assert plan["nitrogen_from_phosphorus_source_kg_per_hectare"] == 18.0


def test_ssp_supplies_no_nitrogen():
    plan = engine.build_plan(n=100, p2o5=48, k2o=0, area_value=1, area_unit="hectare", p_source="ssp")
    by_key = {item["key"]: item for item in plan["products"]}
    assert by_key["ssp"]["kg_per_hectare"] == 300.0
    assert by_key["urea"]["kg_per_hectare"] == pytest.approx(100 / 0.46, abs=0.1)


def test_dap_overshooting_the_nitrogen_dose_is_flagged_not_hidden():
    plan = engine.build_plan(n=10, p2o5=60, k2o=0, area_value=1, area_unit="hectare", p_source="dap")
    assert any("more than your nitrogen dose" in w for w in plan["warnings"])
    assert not [item for item in plan["products"] if item["key"] == "urea"]


def test_phosphorus_and_potassium_are_all_basal_and_nitrogen_is_split():
    plan = engine.build_plan(n=90, p2o5=40, k2o=40, area_value=1, area_unit="hectare", p_source="ssp", n_splits=3)
    stages = [step["stage"] for step in plan["applications"]]
    assert stages[0].startswith("Basal") and len(stages) == 3
    keys = [[i["key"] for i in step["items"]] for step in plan["applications"]]
    assert set(keys[0]) == {"ssp", "mop", "urea"}
    assert keys[1] == ["urea"] and keys[2] == ["urea"]
    urea = [next(i["kg"] for i in step["items"] if i["key"] == "urea") for step in plan["applications"]]
    assert urea[0] == pytest.approx(urea[1], abs=0.1) == pytest.approx(urea[2], abs=0.1)


def test_area_units():
    ha = lambda v, u: engine.to_hectares(v, u)  # noqa: E731
    assert ha(1, "hectare") == 1
    assert ha(1, "acre") == pytest.approx(0.404686)
    assert ha(40, "guntha") == pytest.approx(ha(1, "acre"))
    plan = engine.build_plan(n=40, p2o5=0, k2o=0, area_value=20, area_unit="guntha", n_splits=1)
    assert plan["area"]["acres"] == 0.5
    assert plan["products"][0]["kg_for_area"] == pytest.approx(40 * engine.to_hectares(20, "guntha") / 0.46, abs=0.1)


@pytest.mark.parametrize("nutrient,amount,expected", [
    ("N", 279.9, "low"), ("N", 280, "medium"), ("N", 560, "medium"), ("N", 560.1, "high"),
    ("P", 9.9, "low"), ("P", 10, "medium"), ("P", 25, "medium"), ("P", 25.1, "high"),
    ("K", 119.9, "low"), ("K", 120, "medium"), ("K", 280, "medium"), ("K", 280.1, "high"),
])
def test_rating_boundaries(nutrient, amount, expected):
    assert engine.rate_nutrient(nutrient, amount) == expected


def test_rating_printed_on_the_report_wins_over_a_computed_one():
    soil = {"N": engine.SoilInput(value=100, rating="high"), "P": engine.SoilInput(value=5), "K": engine.SoilInput()}
    out = {item["nutrient"]: item for item in engine.interpret_soil(soil)}
    assert out["N"]["rating"] == "high" and out["N"]["basis"] == "from your report"
    assert out["P"]["rating"] == "low" and out["P"]["basis"] == "computed with default limits"
    assert "K" not in out


@pytest.mark.parametrize("kwargs", [
    dict(n=-1, p2o5=10, k2o=10), dict(n=10, p2o5=601, k2o=0), dict(n=0, p2o5=0, k2o=0),
    dict(n=10, p2o5=0, k2o=0, n_splits=0), dict(n=10, p2o5=0, k2o=0, n_splits=5),
    dict(n=10, p2o5=0, k2o=0, area_value=0), dict(n=10, p2o5=0, k2o=0, area_value=1e9),
])
def test_engine_rejects_invalid_requests(kwargs):
    base = dict(n=10, p2o5=10, k2o=10, area_value=1, area_unit="acre")
    base.update(kwargs)
    with pytest.raises(engine.PlanError):
        engine.build_plan(**base)


def test_every_reference_dose_has_a_source_and_a_verification_level():
    refs = engine.DATA["references"]
    assert len(refs) >= 4 and len({r["id"] for r in refs}) == len(refs)
    for ref in refs:
        assert ref["source_url"].startswith("https://") and ref["source_title"]
        assert ref["verification"] in ("verified", "partly_verified")
        assert 0 <= ref["N"] <= 300 and 0 <= ref["P2O5"] <= 300 and 0 <= ref["K2O"] <= 300


def test_reference_dose_with_a_non_medium_soil_rating_warns_to_prefer_the_card():
    plan = engine.build_plan(n=100, p2o5=50, k2o=50, area_value=1, area_unit="acre", reference_id="cotton-irrigated-mh",
                             soil={"P": engine.SoilInput(rating="low"), "K": engine.SoilInput(rating="medium")})
    text = " ".join(plan["warnings"])
    assert "Phosphorus is rated low" in text and "Potassium" not in text and "Soil Health Card" in text


# ----- HTTP API ------------------------------------------------------------------------------
def post_plan(client, **over):
    body = {"dose_source": "own", "n": 100, "p2o5": 50, "k2o": 50, "area_value": 1, "area_unit": "acre"}
    body.update(over)
    return client.post("/api/fertilizer/plan", json=body)


def test_options_endpoint_lists_sources(client):
    data = client.get("/api/fertilizer/options").json()
    assert {r["id"] for r in data["references"]} >= {"cotton-irrigated-mh", "wheat-irrigated-mpkv"}
    assert data["products"]["urea"]["N"] == 46 and data["products"]["dap"]["P2O5"] == 46
    assert data["rating_limits"]["source_url"].startswith("https://") and data["rating_limits"]["caveat"]


def test_plan_is_saved_and_listed_in_history(client):
    created = post_plan(client, label="  North   plot ")
    assert created.status_code == 200
    body = created.json()
    assert body["label"] == "North plot" and body["id"] and body["created_at"].endswith("Z")
    assert body["disclaimer"] and body["assumptions"]
    history = client.get("/api/fertilizer/history").json()
    assert len(history) == 1 and history[0]["id"] == body["id"] and history[0]["products"] == body["products"]


def test_reference_plan_cites_its_source(client):
    response = post_plan(client, dose_source="reference", reference_id="cotton-irrigated-mh", n=None, p2o5=None, k2o=None, n_splits=3)
    body = response.json()
    assert response.status_code == 200 and body["dose_kg_per_hectare"] == {"N": 100, "P2O5": 50, "K2O": 50}
    assert any("Package of Practices for Cotton" in s["title"] for s in body["sources"])
    assert "Maharashtra" in body["label"]


def test_soil_ratings_are_returned(client):
    body = post_plan(client, soil_n={"value": 200}, soil_p={"rating": "high"}, soil_k={"value": 300}).json()
    ratings = {r["nutrient"]: r["rating"] for r in body["soil_ratings"]}
    assert ratings == {"N": "low", "P": "high", "K": "high"}


@pytest.mark.parametrize("over", [
    {"n": -1}, {"p2o5": 601}, {"n": "abc"}, {"n": None}, {"n": 0, "p2o5": 0, "k2o": 0},
    {"area_value": 0}, {"area_value": -3}, {"area_unit": "bigha"}, {"n_splits": 9}, {"p_source": "urea"},
    {"dose_source": "reference", "reference_id": "nope"}, {"dose_source": "reference", "reference_id": None},
    {"soil_n": {"value": -5}}, {"soil_p": {"rating": "excellent"}}, {"soil_k": {"value": 10**9}}, {"surprise": 1},
])
def test_invalid_plan_requests_are_rejected_and_not_saved(client, over):
    assert post_plan(client, **over).status_code == 422
    assert client.get("/api/fertilizer/history").json() == []


def test_nan_and_infinity_are_rejected(client):
    for raw in ('{"dose_source":"own","n":NaN,"p2o5":1,"k2o":1,"area_value":1,"area_unit":"acre"}',
                '{"dose_source":"own","n":1,"p2o5":1,"k2o":1,"area_value":Infinity,"area_unit":"acre"}'):
        assert client.post("/api/fertilizer/plan", content=raw, headers={"content-type": "application/json"}).status_code == 422


def test_soil_value_limit_is_configurable(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "NPK_MAX_VALUE", 100)
    assert post_plan(client, soil_n={"value": 101}).status_code == 422
    assert post_plan(client, soil_n={"value": 100}).status_code == 200
