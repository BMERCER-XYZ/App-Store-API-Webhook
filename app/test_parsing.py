from .appstore import AppStoreClient


def test_parse_units():
    sample = "Provider\tProvider Country\tSKU\tDeveloper\tTitle\tVersion\tProduct Type Identifier\tUnits\n" \
             "MyVendor\tUS\t123456789\tMe\tMyApp\t1.0\t1\t42\n" \
             "MyVendor\tUS\t123456789\tMe\tMyApp\t1.0\t1\t8\n"
    total = AppStoreClient._parse_units_from_tsv(sample)  # type: ignore
    assert total == 50, f"Expected 50 got {total}"

if __name__ == '__main__':
    test_parse_units()
    print("parse test passed")
