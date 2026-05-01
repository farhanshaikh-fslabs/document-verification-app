from app.db.models import CertificateKind
from app.validation.engine import (
    validate_citation_presence,
    validate_date_manufacture,
    validate_manufacturer_presence,
    validate_place_testing,
    validate_place_manufacture,
    validate_product_identification,
    validate_record_keeper,
)


def test_product_match() -> None:
    cert = {"product_name": "Toy", "product_description": "Red plastic", "identification_numbers": "SKU-1"}
    test = {"product_name": "Toy", "product_description": "Red plastic", "identification_numbers": "SKU-1"}
    r = validate_product_identification(cert, test)
    assert r.passed


def test_product_mismatch() -> None:
    cert = {"product_name": "Toy", "product_description": "Red plastic", "identification_numbers": "SKU-1"}
    test = {"product_name": "Toy", "product_description": "Blue plastic", "identification_numbers": "SKU-1"}
    r = validate_product_identification(cert, test)
    assert not r.passed


def test_citation_symmetric() -> None:
    r = validate_citation_presence(["16 CFR 1610"], ["16 CFR 1610"])
    assert r[0].passed


def test_citation_only_on_cert() -> None:
    r = validate_citation_presence(["16 CFR 1610"], [])
    assert not r[0].passed


def test_manufacturer_presence() -> None:
    ok = validate_manufacturer_presence(
        {"company_name": "Acme", "address": "1 Main St"},
        {"company_name": "Acme", "address": "2 Other Rd"},
    )
    assert ok.passed


def test_record_keeper_cert_required() -> None:
    r = validate_record_keeper(
        {"name": "", "mailing_address": "x", "email": "a@b.co", "telephone": "1"},
        {},
    )
    assert not r.passed


def test_place_manufacture_match() -> None:
    r = validate_place_manufacture(
        {"country": "China", "city_or_factory": "Shenzhen"},
        {"country": "China", "city_or_factory": "Shenzhen"},
    )
    assert r.passed


def test_date_manufacture_optional_both_empty() -> None:
    r = validate_date_manufacture({}, {})
    assert r.passed


def test_date_manufacture_mismatch_when_partial() -> None:
    r = validate_date_manufacture({"month_year_or_range": "Jan 2024"}, {})
    assert not r.passed


def test_third_party_lab_cpc_requires_match() -> None:
    from app.validation.engine import validate_third_party_lab

    c = {
        "laboratory_name": "Lab A",
        "full_address": "1 St, City ST",
        "cpsc_accreditation_number": "LAB-1",
    }
    t = dict(c)
    assert validate_third_party_lab(c, t, CertificateKind.cpc).passed
    t2 = {**c, "cpsc_accreditation_number": "LAB-2"}
    assert not validate_third_party_lab(c, t2, CertificateKind.cpc).passed


def test_citation_presence_accepts_dict_shape() -> None:
    r = validate_citation_presence(
        ["16 CFR Title 16 Part 1303 - Ban of Lead Containing Paint"],
        ["16 CRF Title 16 Part 1303 - Ban of Lead Containing Paint"],
    )
    assert r[0].passed


def test_manufacturer_presence_accepts_alias_keys_and_string() -> None:
    ok = validate_manufacturer_presence(
        {"name": "Essendant Co.", "address": "One Parkway North Boulevard, Deerfield, IL 60015"},
        "Essendant Co., One Parkway North Boulevard, Deerfield, IL 60015, 847-627-7000",
    )
    assert ok.passed


def test_place_testing_accepts_address_alias() -> None:
    r = validate_place_testing(
        {
            "laboratory_name": "Narang Metallurgical & Spectro Services",
            "address": "1E/18, Ground Floor, Jhandewalan Extn, New Delhi 110055",
        },
        {
            "laboratory_name": "Narang Metallurgical & Spectro Services",
            "full_address": "1E/18, Ground Floor, Jhandewalan Extn, New Delhi 110055",
        },
    )
    assert r.passed
