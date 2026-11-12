"""Frozen M10 cohort from non-held-out P1 dense misses."""

DOCUMENTS = {
    "AMCOR_2022_8K_dated-2022-07-01": "1de32e72c265486469f3b1c7cbfbe064a27055e60f7b43a81439986dda9025ad",
    "MGMRESORTS_2022Q4_EARNINGS": "fe9126b17c3656e50d53741b13cb5fb233d4adaf922e4d84072b1d5e564fbfbd",
    "BESTBUY_2024Q2_10Q": "cf9efb922bdd28d726d7e1605c5fa1f263dda72e033989e3bc9ee3a3bb356c03",
    "BESTBUY_2023_10K": "7ca465d31a08be29e8c08d756644d33d818c7254a1215720f265227005cda696",
    "NIKE_2018_10K": "31de66f1e37cabf1785e0ffa66955bf003bf2a9dcf3f4ebe93732d063b7b6ebe",
}
CASE_IDS = frozenset(f"financebench_id_{item}" for item in (
    "01935", "00382", "01911", "01912", "00288", "01902", "00685", "01077", "01275", "04302",
))

# Audit labels are used only by the offline scorer. Page numbers are physical
# PDF indexes starting at zero, even where the filing prints another number.
READING_ORDER = {
    ("AMCOR_2022_8K_dated-2022-07-01", 1): (
        "Other Events", "On June 30 2022", "The foregoing description", "Financial Statements and Exhibits",
    ),
    ("MGMRESORTS_2022Q4_EARNINGS", 12): (
        "Supplemental Data Net Revenues", "Las Vegas Strip Resorts",
        "Adjusted Property EBITDAR", "Represents the Company",
    ),
    ("BESTBUY_2024Q2_10Q", 19): (
        "Consolidated Non GAAP Financial Measures", "Non GAAP operating income",
        "Liquidity and Capital Resources", "Cash and cash equivalents",
    ),
    ("BESTBUY_2023_10K", 50): (
        "Vendor Allowances", "Advertising Costs", "Acquisitions", "Restructuring",
    ),
    ("NIKE_2018_10K", 45): (
        "Consolidated Statements of Income", "Revenues", "Net Income",
        "Dividends declared per common share",
    ),
}

# A row must recover the full ordered value sequence. Native header checks
# then ask whether the actual column spans attach each expected period label.
TABLE_ROWS = (
    ("BESTBUY_2023_10K", 50, "Total", ("147", "-40", "277"), (("2023",), ("2022",), ("2021",))),
    ("BESTBUY_2024Q2_10Q", 19, "Non GAAP operating income", ("362", "427", "684", "912"), (
        ("Three Months Ended", "July 29 2023"), ("Three Months Ended", "July 30 2022"),
        ("Six Months Ended", "July 29 2023"), ("Six Months Ended", "July 30 2022"),
    )),
    ("BESTBUY_2024Q2_10Q", 19, "Cash and cash equivalents", ("1093", "1874", "840"), (
        ("July 29 2023",), ("January 28 2023",), ("July 30 2022",),
    )),
    ("MGMRESORTS_2022Q4_EARNINGS", 12, "Las Vegas Strip Resorts", (
        "2297282", "1806686", "8398372", "4737185",
    ), (
        ("Three months ended", "December 31 2022"), ("Three months ended", "December 31 2021"),
        ("Twelve months ended", "December 31 2022"), ("Twelve months ended", "December 31 2021"),
    )),
    ("NIKE_2018_10K", 45, "Revenues", ("36397", "34350", "32376"), (("2018",), ("2017",), ("2016",))),
    ("NIKE_2018_10K", 45, "Net Income", ("1933", "4240", "3760"), (("2018",), ("2017",), ("2016",))),
)
