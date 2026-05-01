"""Canonical attribute keys for extractions and validations."""

# Product identification (nested JSON value)
ATTR_CERT_PRODUCT = "certificate.product_identification"
ATTR_TEST_PRODUCT = "test_report.product_identification"

# Citations (list of strings in value_json)
ATTR_CERT_CITATIONS = "certificate.citations"
ATTR_TEST_CITATIONS = "test_report.citations"

ATTR_CERT_MANUFACTURER = "certificate.manufacturer_importer"
ATTR_TEST_MANUFACTURER = "test_report.manufacturer_importer"

ATTR_CERT_RECORD_KEEPER = "certificate.record_keeper_contact"
ATTR_TEST_RECORD_KEEPER = "test_report.record_keeper_contact"

ATTR_CERT_PLACE_MANUFACTURE = "certificate.place_of_manufacture"
ATTR_TEST_PLACE_MANUFACTURE = "test_report.place_of_manufacture"

ATTR_CERT_DATE_MANUFACTURE = "certificate.date_of_manufacture"
ATTR_TEST_DATE_MANUFACTURE = "test_report.date_of_manufacture"

ATTR_CERT_PLACE_TESTING = "certificate.place_of_testing"
ATTR_TEST_PLACE_TESTING = "test_report.place_of_testing"

ATTR_CERT_DATE_TESTING = "certificate.date_of_testing"
ATTR_TEST_DATE_TESTING = "test_report.date_of_testing"

ATTR_CERT_THIRD_PARTY_LAB = "certificate.third_party_lab"
ATTR_TEST_THIRD_PARTY_LAB = "test_report.third_party_lab"

ALL_ATTRIBUTE_KEYS = [
    ATTR_CERT_PRODUCT,
    ATTR_TEST_PRODUCT,
    ATTR_CERT_CITATIONS,
    ATTR_TEST_CITATIONS,
    ATTR_CERT_MANUFACTURER,
    ATTR_TEST_MANUFACTURER,
    ATTR_CERT_RECORD_KEEPER,
    ATTR_TEST_RECORD_KEEPER,
    ATTR_CERT_PLACE_MANUFACTURE,
    ATTR_TEST_PLACE_MANUFACTURE,
    ATTR_CERT_DATE_MANUFACTURE,
    ATTR_TEST_DATE_MANUFACTURE,
    ATTR_CERT_PLACE_TESTING,
    ATTR_TEST_PLACE_TESTING,
    ATTR_CERT_DATE_TESTING,
    ATTR_TEST_DATE_TESTING,
    ATTR_CERT_THIRD_PARTY_LAB,
    ATTR_TEST_THIRD_PARTY_LAB,
]
