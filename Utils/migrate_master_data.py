import logging
from sqlalchemy import text
from Model.db import engine, Base
# Ensure all models are imported so Base.metadata knows about them
import Model.containermgmt
from Model.containermgmt.MasterData.Currency import Currency, CurrencyExchangeRate
from Model.containermgmt.MasterData.PaymentTerm import PaymentTerm
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.Organisation import Organisation

logger = logging.getLogger("containerMgmt.migrations")

# Comprehensive ISO-4217 World Currency Seed List (~165+ official currencies)
WORLD_CURRENCIES = [
    # Base / African & Indian Ocean regional currencies
    {"code": "SCR", "name": "Seychelles Rupee", "symbol": "SCR", "decimals": 2, "is_active": True},
    {"code": "MUR", "name": "Mauritian Rupee", "symbol": "Rs", "decimals": 2, "is_active": True},
    {"code": "ZAR", "name": "South African Rand", "symbol": "R", "decimals": 2, "is_active": True},
    {"code": "KES", "name": "Kenyan Shilling", "symbol": "KSh", "decimals": 2, "is_active": True},
    {"code": "TZS", "name": "Tanzanian Shilling", "symbol": "TSh", "decimals": 2, "is_active": True},
    {"code": "UGX", "name": "Ugandan Shilling", "symbol": "USh", "decimals": 0, "is_active": True},
    {"code": "MGA", "name": "Malagasy Ariary", "symbol": "Ar", "decimals": 2, "is_active": False},
    {"code": "KMF", "name": "Comorian Franc", "symbol": "CF", "decimals": 0, "is_active": False},
    {"code": "RWF", "name": "Rwandan Franc", "symbol": "FRw", "decimals": 0, "is_active": False},
    {"code": "BIF", "name": "Burundian Franc", "symbol": "FBu", "decimals": 0, "is_active": False},
    {"code": "ETB", "name": "Ethiopian Birr", "symbol": "Br", "decimals": 2, "is_active": False},
    {"code": "DJF", "name": "Djiboutian Franc", "symbol": "Fdj", "decimals": 0, "is_active": False},
    {"code": "SOS", "name": "Somali Shilling", "symbol": "Sh.So.", "decimals": 2, "is_active": False},
    {"code": "MZN", "name": "Mozambican Metical", "symbol": "MT", "decimals": 2, "is_active": False},
    {"code": "ZMW", "name": "Zambian Kwacha", "symbol": "ZK", "decimals": 2, "is_active": False},
    {"code": "BWP", "name": "Botswana Pula", "symbol": "P", "decimals": 2, "is_active": False},
    {"code": "NAD", "name": "Namibian Dollar", "symbol": "N$", "decimals": 2, "is_active": False},
    {"code": "SZL", "name": "Eswatini Lilangeni", "symbol": "L", "decimals": 2, "is_active": False},
    {"code": "LSL", "name": "Lesotho Loti", "symbol": "L", "decimals": 2, "is_active": False},
    {"code": "AOA", "name": "Angolan Kwanza", "symbol": "Kz", "decimals": 2, "is_active": False},
    {"code": "NGN", "name": "Nigerian Naira", "symbol": "₦", "decimals": 2, "is_active": False},
    {"code": "GHS", "name": "Ghanaian Cedi", "symbol": "GH₵", "decimals": 2, "is_active": False},
    {"code": "XOF", "name": "West African CFA Franc", "symbol": "CFA", "decimals": 0, "is_active": False},
    {"code": "XAF", "name": "Central African CFA Franc", "symbol": "FCFA", "decimals": 0, "is_active": False},
    {"code": "GMD", "name": "Gambian Dalasi", "symbol": "D", "decimals": 2, "is_active": False},
    {"code": "SLL", "name": "Sierra Leonean Leone", "symbol": "Le", "decimals": 2, "is_active": False},
    {"code": "LRD", "name": "Liberian Dollar", "symbol": "L$", "decimals": 2, "is_active": False},
    {"code": "GNF", "name": "Guinean Franc", "symbol": "FG", "decimals": 0, "is_active": False},
    {"code": "CVE", "name": "Cape Verdean Escudo", "symbol": "Esc", "decimals": 2, "is_active": False},
    {"code": "STN", "name": "São Tomé and Príncipe Dobra", "symbol": "Db", "decimals": 2, "is_active": False},
    {"code": "EGP", "name": "Egyptian Pound", "symbol": "E£", "decimals": 2, "is_active": False},
    {"code": "MAD", "name": "Moroccan Dirham", "symbol": "DH", "decimals": 2, "is_active": False},
    {"code": "DZD", "name": "Algerian Dinar", "symbol": "DA", "decimals": 2, "is_active": False},
    {"code": "TND", "name": "Tunisian Dinar", "symbol": "DT", "decimals": 3, "is_active": False},
    {"code": "LYD", "name": "Libyan Dinar", "symbol": "LD", "decimals": 3, "is_active": False},
    {"code": "SDG", "name": "Sudanese Pound", "symbol": "SDG", "decimals": 2, "is_active": False},
    {"code": "ZWL", "name": "Zimbabwean Dollar", "symbol": "ZWL$", "decimals": 2, "is_active": False},

    # Major Global Currencies
    {"code": "USD", "name": "US Dollar", "symbol": "$", "decimals": 2, "is_active": True},
    {"code": "EUR", "name": "Euro", "symbol": "€", "decimals": 2, "is_active": True},
    {"code": "GBP", "name": "British Pound", "symbol": "£", "decimals": 2, "is_active": True},
    {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥", "decimals": 2, "is_active": True},
    {"code": "AED", "name": "UAE Dirham", "symbol": "AED", "decimals": 2, "is_active": True},
    {"code": "INR", "name": "Indian Rupee", "symbol": "₹", "decimals": 2, "is_active": True},
    {"code": "SGD", "name": "Singapore Dollar", "symbol": "S$", "decimals": 2, "is_active": True},
    {"code": "JPY", "name": "Japanese Yen", "symbol": "¥", "decimals": 0, "is_active": True},
    {"code": "CAD", "name": "Canadian Dollar", "symbol": "CA$", "decimals": 2, "is_active": True},
    {"code": "AUD", "name": "Australian Dollar", "symbol": "A$", "decimals": 2, "is_active": True},
    {"code": "CHF", "name": "Swiss Franc", "symbol": "CHF", "decimals": 2, "is_active": True},
    {"code": "HKD", "name": "Hong Kong Dollar", "symbol": "HK$", "decimals": 2, "is_active": True},
    {"code": "NZD", "name": "New Zealand Dollar", "symbol": "NZ$", "decimals": 2, "is_active": True},

    # Middle East
    {"code": "SAR", "name": "Saudi Riyal", "symbol": "SAR", "decimals": 2, "is_active": True},
    {"code": "QAR", "name": "Qatari Riyal", "symbol": "QAR", "decimals": 2, "is_active": True},
    {"code": "KWD", "name": "Kuwaiti Dinar", "symbol": "KD", "decimals": 3, "is_active": True},
    {"code": "BHD", "name": "Bahraini Dinar", "symbol": "BD", "decimals": 3, "is_active": True},
    {"code": "OMR", "name": "Omani Rial", "symbol": "OMR", "decimals": 3, "is_active": True},
    {"code": "JOD", "name": "Jordanian Dinar", "symbol": "JD", "decimals": 3, "is_active": False},
    {"code": "ILS", "name": "Israeli New Shekel", "symbol": "₪", "decimals": 2, "is_active": False},
    {"code": "IQD", "name": "Iraqi Dinar", "symbol": "IQD", "decimals": 3, "is_active": False},
    {"code": "IRR", "name": "Iranian Rial", "symbol": "IRR", "decimals": 2, "is_active": False},
    {"code": "SYP", "name": "Syrian Pound", "symbol": "LS", "decimals": 2, "is_active": False},
    {"code": "YER", "name": "Yemeni Rial", "symbol": "YR", "decimals": 2, "is_active": False},
    {"code": "LBP", "name": "Lebanese Pound", "symbol": "L£", "decimals": 2, "is_active": False},

    # Asia & Pacific
    {"code": "THB", "name": "Thai Baht", "symbol": "฿", "decimals": 2, "is_active": True},
    {"code": "MYR", "name": "Malaysian Ringgit", "symbol": "RM", "decimals": 2, "is_active": True},
    {"code": "IDR", "name": "Indonesian Rupiah", "symbol": "Rp", "decimals": 0, "is_active": True},
    {"code": "PHP", "name": "Philippine Peso", "symbol": "₱", "decimals": 2, "is_active": True},
    {"code": "VND", "name": "Vietnamese Dong", "symbol": "₫", "decimals": 0, "is_active": True},
    {"code": "KRW", "name": "South Korean Won", "symbol": "₩", "decimals": 0, "is_active": True},
    {"code": "TWD", "name": "New Taiwan Dollar", "symbol": "NT$", "decimals": 2, "is_active": True},
    {"code": "PKR", "name": "Pakistani Rupee", "symbol": "PKR", "decimals": 2, "is_active": False},
    {"code": "BDT", "name": "Bangladeshi Taka", "symbol": "৳", "decimals": 2, "is_active": False},
    {"code": "LKR", "name": "Sri Lankan Rupee", "symbol": "Rs", "decimals": 2, "is_active": False},
    {"code": "NPR", "name": "Nepalese Rupee", "symbol": "NPRs", "decimals": 2, "is_active": False},
    {"code": "KZT", "name": "Kazakhstani Tenge", "symbol": "₸", "decimals": 2, "is_active": False},
    {"code": "UZS", "name": "Uzbekistani Som", "symbol": "UZS", "decimals": 2, "is_active": False},
    {"code": "TMT", "name": "Turkmenistan Manat", "symbol": "TMT", "decimals": 2, "is_active": False},
    {"code": "TJS", "name": "Tajikistani Somoni", "symbol": "TJS", "decimals": 2, "is_active": False},
    {"code": "KGS", "name": "Kyrgyzstani Som", "symbol": "KGS", "decimals": 2, "is_active": False},
    {"code": "MNT", "name": "Mongolian Tugrik", "symbol": "₮", "decimals": 2, "is_active": False},
    {"code": "KHR", "name": "Cambodian Riel", "symbol": "៛", "decimals": 2, "is_active": False},
    {"code": "LAK", "name": "Lao Kip", "symbol": "₭", "decimals": 2, "is_active": False},
    {"code": "MMK", "name": "Myanmar Kyat", "symbol": "K", "decimals": 2, "is_active": False},
    {"code": "BND", "name": "Brunei Dollar", "symbol": "B$", "decimals": 2, "is_active": False},
    {"code": "MVR", "name": "Maldivian Rufiyaa", "symbol": "Rf", "decimals": 2, "is_active": False},
    {"code": "BTN", "name": "Bhutanese Ngultrum", "symbol": "Nu.", "decimals": 2, "is_active": False},
    {"code": "FJD", "name": "Fijian Dollar", "symbol": "FJ$", "decimals": 2, "is_active": False},
    {"code": "PGK", "name": "Papua New Guinean Kina", "symbol": "K", "decimals": 2, "is_active": False},
    {"code": "SBD", "name": "Solomon Islands Dollar", "symbol": "SI$", "decimals": 2, "is_active": False},
    {"code": "VUV", "name": "Vanuatu Vatu", "symbol": "VT", "decimals": 0, "is_active": False},
    {"code": "WST", "name": "Samoan Tala", "symbol": "WS$", "decimals": 2, "is_active": False},
    {"code": "TOP", "name": "Tongan Paʻanga", "symbol": "T$", "decimals": 2, "is_active": False},
    {"code": "XPF", "name": "CFP Franc", "symbol": "₣", "decimals": 0, "is_active": False},

    # Europe (Non-Euro)
    {"code": "SEK", "name": "Swedish Krona", "symbol": "kr", "decimals": 2, "is_active": False},
    {"code": "NOK", "name": "Norwegian Krone", "symbol": "kr", "decimals": 2, "is_active": False},
    {"code": "DKK", "name": "Danish Krone", "symbol": "kr.", "decimals": 2, "is_active": False},
    {"code": "ISK", "name": "Icelandic Króna", "symbol": "kr", "decimals": 0, "is_active": False},
    {"code": "PLN", "name": "Polish Zloty", "symbol": "zł", "decimals": 2, "is_active": False},
    {"code": "CZK", "name": "Czech Koruna", "symbol": "Kč", "decimals": 2, "is_active": False},
    {"code": "HUF", "name": "Hungarian Forint", "symbol": "Ft", "decimals": 2, "is_active": False},
    {"code": "RON", "name": "Romanian Leu", "symbol": "lei", "decimals": 2, "is_active": False},
    {"code": "BGN", "name": "Bulgarian Lev", "symbol": "лв", "decimals": 2, "is_active": False},
    {"code": "TRY", "name": "Turkish Lira", "symbol": "₺", "decimals": 2, "is_active": True},
    {"code": "RUB", "name": "Russian Ruble", "symbol": "₽", "decimals": 2, "is_active": False},
    {"code": "RSD", "name": "Serbian Dinar", "symbol": "din.", "decimals": 2, "is_active": False},
    {"code": "BAM", "name": "Bosnia and Herzegovina Convertible Mark", "symbol": "KM", "decimals": 2, "is_active": False},
    {"code": "MKD", "name": "Macedonian Denar", "symbol": "ден", "decimals": 2, "is_active": False},
    {"code": "ALL", "name": "Albanian Lek", "symbol": "Lek", "decimals": 2, "is_active": False},
    {"code": "MDL", "name": "Moldovan Leu", "symbol": "MDL", "decimals": 2, "is_active": False},
    {"code": "UAH", "name": "Ukrainian Hryvnia", "symbol": "₴", "decimals": 2, "is_active": False},
    {"code": "BYN", "name": "Belarusian Ruble", "symbol": "Br", "decimals": 2, "is_active": False},
    {"code": "GEL", "name": "Georgian Lari", "symbol": "₾", "decimals": 2, "is_active": False},
    {"code": "AMD", "name": "Armenian Dram", "symbol": "֏", "decimals": 2, "is_active": False},
    {"code": "AZN", "name": "Azerbaijani Manat", "symbol": "₼", "decimals": 2, "is_active": False},

    # Americas & Caribbean
    {"code": "BRL", "name": "Brazilian Real", "symbol": "R$", "decimals": 2, "is_active": True},
    {"code": "MXN", "name": "Mexican Peso", "symbol": "Mex$", "decimals": 2, "is_active": True},
    {"code": "ARS", "name": "Argentine Peso", "symbol": "$", "decimals": 2, "is_active": False},
    {"code": "CLP", "name": "Chilean Peso", "symbol": "CLP$", "decimals": 0, "is_active": False},
    {"code": "COP", "name": "Colombian Peso", "symbol": "COL$", "decimals": 2, "is_active": False},
    {"code": "PEN", "name": "Peruvian Sol", "symbol": "S/.", "decimals": 2, "is_active": False},
    {"code": "UYU", "name": "Uruguayan Peso", "symbol": "$U", "decimals": 2, "is_active": False},
    {"code": "PYG", "name": "Paraguayan Guarani", "symbol": "₲", "decimals": 0, "is_active": False},
    {"code": "BOB", "name": "Bolivian Boliviano", "symbol": "Bs.", "decimals": 2, "is_active": False},
    {"code": "VES", "name": "Venezuelan Bolívar", "symbol": "Bs.", "decimals": 2, "is_active": False},
    {"code": "GYD", "name": "Guyanese Dollar", "symbol": "G$", "decimals": 2, "is_active": False},
    {"code": "SRD", "name": "Surinamese Dollar", "symbol": "Sr$", "decimals": 2, "is_active": False},
    {"code": "TTD", "name": "Trinidad and Tobago Dollar", "symbol": "TT$", "decimals": 2, "is_active": False},
    {"code": "JMD", "name": "Jamaican Dollar", "symbol": "J$", "decimals": 2, "is_active": False},
    {"code": "BSD", "name": "Bahamian Dollar", "symbol": "B$", "decimals": 2, "is_active": False},
    {"code": "BBD", "name": "Barbadian Dollar", "symbol": "Bds$", "decimals": 2, "is_active": False},
    {"code": "BZD", "name": "Belize Dollar", "symbol": "BZ$", "decimals": 2, "is_active": False},
    {"code": "HTG", "name": "Haitian Gourde", "symbol": "G", "decimals": 2, "is_active": False},
    {"code": "DOP", "name": "Dominican Peso", "symbol": "RD$", "decimals": 2, "is_active": False},
    {"code": "CUP", "name": "Cuban Peso", "symbol": "₱", "decimals": 2, "is_active": False},
    {"code": "GTQ", "name": "Guatemalan Quetzal", "symbol": "Q", "decimals": 2, "is_active": False},
    {"code": "HNL", "name": "Honduran Lempira", "symbol": "L", "decimals": 2, "is_active": False},
    {"code": "NIO", "name": "Nicaraguan Córdoba", "symbol": "C$", "decimals": 2, "is_active": False},
    {"code": "CRC", "name": "Costa Rican Colón", "symbol": "₡", "decimals": 2, "is_active": False},
    {"code": "PAB", "name": "Panamanian Balboa", "symbol": "B/.", "decimals": 2, "is_active": False},
    {"code": "AWG", "name": "Aruban Florin", "symbol": "Afl.", "decimals": 2, "is_active": False},
    {"code": "ANG", "name": "Netherlands Antillean Guilder", "symbol": "NAƒ", "decimals": 2, "is_active": False},
    {"code": "KYD", "name": "Cayman Islands Dollar", "symbol": "CI$", "decimals": 2, "is_active": False},
    {"code": "BMD", "name": "Bermudian Dollar", "symbol": "BD$", "decimals": 2, "is_active": False},
    {"code": "XCD", "name": "East Caribbean Dollar", "symbol": "EC$", "decimals": 2, "is_active": False},
]

# Baseline standard exchange rates against local base currency SCR
INITIAL_EXCHANGE_RATES_SCR = [
    {"from_currency": "SCR", "to_currency": "SCR", "rate": 1.000000},
    {"from_currency": "USD", "to_currency": "SCR", "rate": 14.500000},
    {"from_currency": "EUR", "to_currency": "SCR", "rate": 15.800000},
    {"from_currency": "GBP", "to_currency": "SCR", "rate": 18.700000},
    {"from_currency": "CNY", "to_currency": "SCR", "rate": 2.050000},
    {"from_currency": "AED", "to_currency": "SCR", "rate": 3.950000},
    {"from_currency": "INR", "to_currency": "SCR", "rate": 0.170000},
    {"from_currency": "ZAR", "to_currency": "SCR", "rate": 0.800000},
    {"from_currency": "SGD", "to_currency": "SCR", "rate": 11.200000},
]

# Standard Payment Terms Templates
STANDARD_PAYMENT_TERMS = [
    {
        "code": "ADV_30_BL_70",
        "name": "30% Advance, 70% against B/L",
        "description": "30% initial deposit on purchase order confirmation; 70% balance clearance upon receipt of draft Bill of Lading.",
        "advance_pct": 30.00,
        "progress_pct": 0.00,
        "balance_pct": 70.00,
        "balance_trigger": "ON_BL",
        "credit_days": 0,
    },
    {
        "code": "ADV_100",
        "name": "100% Advance Deposit",
        "description": "Full 100% advance payment required prior to production / container loading.",
        "advance_pct": 100.00,
        "progress_pct": 0.00,
        "balance_pct": 0.00,
        "balance_trigger": "PI_CONFIRMATION",
        "credit_days": 0,
    },
    {
        "code": "ADV_50_DISP_50",
        "name": "50% Advance, 50% on Dispatch",
        "description": "50% deposit upon order placement; 50% balance before cargo leaves supplier facility / port of loading.",
        "advance_pct": 50.00,
        "progress_pct": 0.00,
        "balance_pct": 50.00,
        "balance_trigger": "ON_DISPATCH",
        "credit_days": 0,
    },
    {
        "code": "NET_30",
        "name": "Net 30 Days from Delivery",
        "description": "0% advance deposit; 100% payment due 30 days after goods arrival and inspection.",
        "advance_pct": 0.00,
        "progress_pct": 0.00,
        "balance_pct": 100.00,
        "balance_trigger": "ON_ARRIVAL",
        "credit_days": 30,
    },
    {
        "code": "NET_60",
        "name": "Net 60 Days from Delivery",
        "description": "0% advance deposit; 100% payment due 60 days post-delivery under trade credit agreement.",
        "advance_pct": 0.00,
        "progress_pct": 0.00,
        "balance_pct": 100.00,
        "balance_trigger": "ON_ARRIVAL",
        "credit_days": 60,
    },
    {
        "code": "LC_AT_SIGHT",
        "name": "100% Letter of Credit (LC) at Sight",
        "description": "Irrevocable documentary Letter of Credit payable at sight against shipping documents.",
        "advance_pct": 0.00,
        "progress_pct": 0.00,
        "balance_pct": 100.00,
        "balance_trigger": "ON_BL",
        "credit_days": 0,
    },
]

def ensure_master_data_schema():
    """
    Idempotent schema upgrade for Master Data & Multi-Currency:
    1. Adds base_currency column to usercredentials.organisations.
    2. Ensures currencies, currency_exchange_rates, payment_terms tables exist.
    3. Adds vendor binding columns to containermgmt.supplier.
    4. Seeds currencies, exchange rates, and payment terms.
    """
    try:
        # Step 1: Create all tables defined in metadata
        Base.metadata.create_all(bind=engine)
        logger.info("Master Data tables verified via metadata create_all.")

        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                # Step 2: Ensure base_currency on organisations
                conn.execute(text("""
                    ALTER TABLE usercredentials.organisations
                    ADD COLUMN IF NOT EXISTS base_currency VARCHAR(10) NOT NULL DEFAULT 'SCR';

                    UPDATE usercredentials.organisations
                    SET base_currency = 'SCR'
                    WHERE base_currency IS NULL OR base_currency = '';
                """))

                # Step 3: Ensure supplier columns exist and set defaults for audit mixin columns
                conn.execute(text("""
                    ALTER TABLE containermgmt.currency_exchange_rates
                    ALTER COLUMN is_deleted SET DEFAULT FALSE;

                    ALTER TABLE containermgmt.payment_terms
                    ALTER COLUMN is_deleted SET DEFAULT FALSE;

                    ALTER TABLE containermgmt.supplier
                    ADD COLUMN IF NOT EXISTS code VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS phone VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS contact_person VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS country VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500),
                    ADD COLUMN IF NOT EXISTS default_currency VARCHAR(10) DEFAULT 'USD',
                    ADD COLUMN IF NOT EXISTS default_payment_term_id INTEGER REFERENCES containermgmt.payment_terms(id) ON DELETE SET NULL,
                    ADD COLUMN IF NOT EXISTS notes TEXT,
                    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

                    ALTER TABLE containermgmt.products
                    ALTER COLUMN country_of_origin TYPE VARCHAR(100);

                    ALTER TABLE containermgmt.products
                    ADD COLUMN IF NOT EXISTS videos JSON;
                """))
                conn.commit()

                # Step 4: Seed Currencies
                for cur in WORLD_CURRENCIES:
                    conn.execute(text("""
                        INSERT INTO containermgmt.currencies (code, name, symbol, decimals, is_active, created_at, updated_at)
                        VALUES (:code, :name, :symbol, :decimals, :is_active, NOW(), NOW())
                        ON CONFLICT (code) DO UPDATE
                        SET name = EXCLUDED.name,
                            symbol = EXCLUDED.symbol,
                            decimals = EXCLUDED.decimals;
                    """), cur)

                # Step 5: Seed Baseline Exchange Rates (Global fallback org_id is NULL)
                for rate in INITIAL_EXCHANGE_RATES_SCR:
                    conn.execute(text("""
                        INSERT INTO containermgmt.currency_exchange_rates (org_id, from_currency, to_currency, rate, effective_date, is_active, is_deleted)
                        SELECT NULL, :from_currency, :to_currency, :rate, CURRENT_DATE, TRUE, FALSE
                        WHERE NOT EXISTS (
                            SELECT 1 FROM containermgmt.currency_exchange_rates
                            WHERE org_id IS NULL AND from_currency = :from_currency AND to_currency = :to_currency
                        );
                    """), rate)

                # Step 6: Seed Standard Payment Terms
                for term in STANDARD_PAYMENT_TERMS:
                    conn.execute(text("""
                        INSERT INTO containermgmt.payment_terms (code, name, description, advance_pct, progress_pct, balance_pct, balance_trigger, credit_days, is_active, is_deleted)
                        VALUES (:code, :name, :description, :advance_pct, :progress_pct, :balance_pct, :balance_trigger, :credit_days, TRUE, FALSE)
                        ON CONFLICT (code) DO UPDATE
                        SET name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            advance_pct = EXCLUDED.advance_pct,
                            progress_pct = EXCLUDED.progress_pct,
                            balance_pct = EXCLUDED.balance_pct,
                            balance_trigger = EXCLUDED.balance_trigger,
                            credit_days = EXCLUDED.credit_days;
                    """), term)

                conn.commit()
                logger.info("Master Data currencies, exchange rates, and payment terms successfully verified and seeded.")
    except Exception as e:
        logger.error(f"Error executing Master Data schema migration: {e}", exc_info=True)
