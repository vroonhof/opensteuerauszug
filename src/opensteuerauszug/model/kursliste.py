"""
Model for the Swiss "Kursliste" (price list) format based on kursliste-2.0.0.xsd.

The Kursliste is a standardized format used by Swiss financial institutions
to report security prices for tax purposes.
"""
import datetime
import sys
import lxml.etree as ET
from decimal import Decimal
from enum import Enum
from pathlib import Path
# Add Any for type hinting the validator function
from typing import Any, ClassVar, Dict, List, Literal, Optional, Set, Union
# Removed io import as debugging is removed

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints,
                      ValidationError, field_validator)
from typing_extensions import Annotated
from pydantic_xml import BaseXmlModel as PydanticXmlModel, attr, element

# --- Namespace ---
KURSLISTE_NS = "http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NSMAP = {'': KURSLISTE_NS, 'xsi': XSI_NS}

# --- Base Types & Enums based on XSD Simple Types ---

class CantonBFS(str, Enum):
    AG = "AG"; AI = "AI"; AR = "AR"; BE = "BE"; BL = "BL"; BS = "BS"; FR = "FR"; GE = "GE"
    GL = "GL"; GR = "GR"; JU = "JU"; LU = "LU"; NE = "NE"; NW = "NW"; OW = "OW"; SG = "SG"
    SH = "SH"; SO = "SO"; SZ = "SZ"; TG = "TG"; TI = "TI"; UR = "UR"; VD = "VD"; VS = "VS"
    ZG = "ZG"; ZH = "ZH"

class CapitalContributionStatus(str, Enum):
    APPROVED = "APPROVED"
    NOTAPPROVED = "NOTAPPROVED"

class CountryISO2(str):
    pass

class CurrencyISO3(str):
    pass

class Da1RateType(str, Enum):
    T10P = "10%+"
    T10P_1Y = "10%+.1Y"; T10P_2Y = "10%+.2Y"
    T20P = "20%+"
    T20P_1Y = "20%+.1Y"; T20P_2Y = "20%+.2Y"
    T25P = "25%+"
    T25P_1Y = "25%+.1Y"; T25P_2Y = "25%+.2Y"
    T50P = "50%+"
    T50P_1Y = "50%+.1Y"; T50P_2Y = "50%+.2Y"
    LP = "LP"
    LP_10P = "LP.10%+"; LP_20P = "LP.20%+"; LP_25P = "LP.25%+"; LP_50P = "LP.50%+"
    RPF = "RPF"
    RPF_10P = "RPF.10%+"; RPF_20P = "RPF.20%+"; RPF_25P = "RPF.25%+"; RPF_50P = "RPF.50%+"
    OTHER = "OTHER"

class IncomeType(str, Enum):
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    MIXED = "MIXED"

class InterestType(str, Enum):
    FIX = "FIX"
    VAR = "VAR"

class LangISO2(str, Enum):
    DE = "de"; EN = "en"; FR = "fr"; IT = "it"

class LegalFormBUR(str, Enum):
    F01="01"; F02="02"; F03="03"; F04="04"; F05="05"; F06="06"; F07="07"; F08="08"; F09="09"
    F10="10"; F11="11"; F12="12"; F13="13"; F20="20"; F21="21"; F22="22"; F23="23"; F24="24"
    F25="25"; F27="27"; F28="28"; F29="29"; F30="30"; F31="31"; F32="32"; F33="33"; F34="34"

class PaymentTypeESTV(str, Enum):
    STANDARD = "0"
    GRATIS = "1"
    OTHER_BENEFIT = "2"
    AGIO = "3"
    FUND_ACCUMULATION = "5"

class QuotationType(str, Enum):
    PERCENT = "PERCENT"
    PIECE = "PIECE"

class SectorISIC(str, Enum):
    A="A"; B="B"; C="C"; D="D"; E="E"; F="F"; G="G"; H="H"; I="I"; J="J"

class SecurityGroupESTV(str, Enum):
    BOND="BOND"; COINBULL="COINBULL"; CURRNOTE="CURRNOTE"; DEVT="DEVT"; FUND="FUND"
    LIBOSWAP="LIBOSWAP"; OPTION="OPTION"; OTHER="OTHER"; SHARE="SHARE"

class SecurityTypeESTV(str, Enum):
    BOND_BOND="BOND.BOND"; BOND_CONVERTIBLE="BOND.CONVERTIBLE"; BOND_OPTION="BOND.OPTION"
    COINBULL_COINGOLD="COINBULL.COINGOLD"; COINBULL_GOLD="COINBULL.GOLD"
    COINBULL_PALLADIUM="COINBULL.PALLADIUM"; COINBULL_PLATINUM="COINBULL.PLATINUM"
    COINBULL_SILVER="COINBULL.SILVER"; CURRNOTE_CURRENCY="CURRNOTE.CURRENCY"
    CURRNOTE_CURRYEAR="CURRNOTE.CURRYEAR"; CURRNOTE_TOKEN="CURRNOTE.TOKEN"
    DEVT_COMBINEDPRODUCT="DEVT.COMBINEDPRODUCT"; DEVT_FUNDSIMILARASSET="DEVT.FUNDSIMILARASSET"
    DEVT_INDEXBASKET="DEVT.INDEXBASKET"; FUND_ACCUMULATION="FUND.ACCUMULATION"
    FUND_DISTRIBUTION="FUND.DISTRIBUTION"; FUND_REALESTATE="FUND.REALESTATE"
    LIBOSWAP_LIBOR="LIBOSWAP.LIBOR"; LIBOSWAP_SWAP="LIBOSWAP.SWAP"
    OPTION_CALL="OPTION.CALL"; OPTION_PHANTOM="OPTION.PHANTOM"; OPTION_PUT="OPTION.PUT"
    SHARE_BEARERCERT="SHARE.BEARERCERT"; SHARE_BONUS="SHARE.BONUS"; SHARE_COMMON="SHARE.COMMON"
    SHARE_COOP="SHARE.COOP"; SHARE_LIMITED="SHARE.LIMITED"; SHARE_LIMITEDOLD="SHARE.LIMITEDOLD"
    SHARE_NOMINAL="SHARE.NOMINAL"; SHARE_PARTCERT="SHARE.PARTCERT"
    SHARE_PREFERRED="SHARE.PREFERRED"; SHARE_TRANSFERABLE="SHARE.TRANSFERABLE"

class Source(str, Enum):
    KURSLISTE = "KURSLISTE"
    OTHERQUOTED = "OTHERQUOTED"
    NONQUOTED = "NONQUOTED"

class Validity(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    DEFINITIVE = "DEFINITIVE"
    DEFINITIVE_CORRECTION = "DEFINITIVE.CORRECTION"
    DEFINITIVE_EXTENSION = "DEFINITIVE.EXTENSION"

class WeightUnit(str, Enum):
    GRAM = "GRAM"; OUNCE = "OUNCE"; TOLA = "TOLA"

# Annotated Types for Constraints
# Annotated[..., Field(...)] seems to see corrupted data in some cases???
Percent = Decimal #Annotated[Decimal, Field(decimal_places=10, max_digits=25)]
ValorNumber = int # bAnnotated[int, Field(ge=1, le=999999999999)]
IsinStr = Annotated[str, StringConstraints(min_length=12, max_length=12)]
CurrencyCode = Annotated[str, StringConstraints(min_length=3, max_length=3)]
CountryCode = Annotated[str, StringConstraints(min_length=2, max_length=2)]
Text4000 = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
InstitutionNameStr = Annotated[str, StringConstraints(min_length=1, max_length=120)]
SecurityNameStr = Annotated[str, StringConstraints(min_length=1, max_length=120)]
UidStr = str # Annotated[str, StringConstraints(min_length=12, max_length=12)]
TidType = Annotated[int, Field(ge=15000000, le=17999999)]

# --- Base Model for Entities with ID ---
class Entity(PydanticXmlModel, nsmap=NSMAP):
    """Base type for elements with id and deleted attributes."""
    id: int = attr(use="required")
    deleted: Optional[bool] = attr(default=False)

# --- Complex Types from XSD ---

class LangName(PydanticXmlModel, nsmap=NSMAP):
    """kursliste:langName complex type"""
    lang: LangISO2 = attr(use="required")
    name: Text4000 = attr(use="required")

class LangText(PydanticXmlModel):
    """kursliste:langText complex type"""
    lang: LangISO2 = attr(use="required")
    canton: Optional[CantonBFS] = attr(default=None)
    entryDate: Optional[datetime.datetime] = attr(default=None)
    email: Optional[Annotated[str, StringConstraints(pattern=r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9._-]+\.[A-Za-z]{2,5}")]] = attr(default=None)
    text: Text4000 = attr(use="required")

class LangTextMixed(PydanticXmlModel):
    """kursliste:langTextMixed complex type"""
    lang: Optional[LangISO2] = attr(default=None)
    canton: Optional[CantonBFS] = attr(default=None)
    entryDate: Optional[datetime.datetime] = attr(default=None)
    email: Optional[Annotated[str, StringConstraints(pattern=r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9._-]+\.[A-Za-z]{2,5}")]] = attr(default=None)
    value: str = Field(alias='__text__')

class Remark(LangText):
    pass

class Legend(Entity, tag="legend"):
    """kursliste:legend complex type"""
    text: List[LangTextMixed] = element(tag="text", default_factory=list)
    effectiveDate: Optional[datetime.date] = attr(default=None)
    effectiveDateTo: Optional[datetime.date] = attr(default=None)
    effectiveOrder: Optional[Annotated[int, Field(ge=1)]] = attr(default=1)
    exchangeRatioAvailable: Optional[bool] = attr(default=None)
    exchangeRatioPresent: Optional[Decimal] = attr(default=None)
    exchangeRatioNew: Optional[Decimal] = attr(default=None)
    valorNumberNew: Optional[ValorNumber] = attr(default=None)
    sign: Optional[Annotated[str, StringConstraints(min_length=3, max_length=4)]] = attr(default=None)
    currencyOld: Optional[CurrencyCode] = attr(default=None)
    currencyNew: Optional[CurrencyCode] = attr(default=None)
    nominalValueOld: Optional[Decimal] = attr(default=None)
    nominalValueNew: Optional[Decimal] = attr(default=None)



class Daily(PydanticXmlModel, tag="daily"):
    """kursliste:daily complex type"""
    remark: List[Remark] = element(tag="remark", default_factory=list)
    date: datetime.date = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    quotationType: QuotationType = attr(use="required")
    nominalValue: Optional[Decimal] = attr(default=None)
    percent: Optional[Percent] = attr(default=None)
    taxValue: Optional[Decimal] = attr(default=None)
    exchangeRate: Optional[Decimal] = attr(default=None)
    taxValueCHF: Optional[Decimal] = attr(default=None)
    taxValueCHFBL: Optional[Decimal] = attr(default=None)
    undefined: Optional[bool] = attr(default=False)



class Bondfloor(PydanticXmlModel, tag="bondfloor"):
    """kursliste:bondfloor complex type"""
    remark: List[Remark] = element(tag="remark", default_factory=list)
    date: datetime.date = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    quotationType: Optional[QuotationType] = attr(default=QuotationType.PERCENT)
    nominalValue: Optional[Decimal] = attr(default=None)
    percent: Optional[Percent] = attr(default=None)
    taxValue: Optional[Decimal] = attr(default=None)
    exchangeRate: Optional[Decimal] = attr(default=None)
    taxValueCHF: Optional[Decimal] = attr(default=None)
    undefined: Optional[bool] = attr(default=False)



class Yearend(Entity, tag="yearend"):
    """kursliste:yearend complex type"""
    remark: List[Remark] = element(tag="remark", default_factory=list)
    quotationType: QuotationType = attr(use="required")
    percent: Optional[Percent] = attr(default=None)
    taxValue: Optional[Decimal] = attr(default=None)
    exchangeRate: Optional[Decimal] = attr(default=None)
    taxValueCHF: Optional[Decimal] = attr(default=None)
    taxValueCHFBL: Optional[Decimal] = attr(default=None)
    undefined: Optional[bool] = attr(default=False)



class YearendCurrencyNote(Yearend, tag="yearend"):
    """kursliste:yearendCurrencyNote complex type"""
    taxValueCHFNote: Optional[Decimal] = attr(default=None)
    taxValueCHFMiddle: Optional[Decimal] = attr(default=None)


class YearendGrossNet(Yearend, tag="yearend"):
    """kursliste:yearendGrossNet complex type"""
    percentNet: Optional[Percent] = attr(default=None)
    percentNetNet: Optional[Percent] = attr(default=None)
    taxValueCHFNet: Optional[Decimal] = attr(default=None)
    taxValueCHFNetNet: Optional[Decimal] = attr(default=None)
    rectificate: Optional[bool] = attr(default=False)
    rectificateInProgress: Optional[bool] = attr(default=False)
    taxRelevantChange: Optional[bool] = attr(default=False)
    usePreviousYear: Optional[bool] = attr(default=False)
    canton: Optional[CantonBFS] = attr(default=None)
    uid: Optional[UidStr] = attr(default=None)
    ahvNumber: Optional[Annotated[str, StringConstraints(min_length=13, max_length=13)]] = attr(default=None)



class YearendInstitution(Entity, tag="yearend"):
     """kursliste:yearendInstitution complex type"""
     quotationType: QuotationType = attr(use="required")
     percent: Optional[Percent] = attr(default=None)
     totalTaxValue: Optional[Decimal] = attr(default=None)
     exchangeRate: Optional[Decimal] = attr(default=None)
     totalTaxValueCHF: Optional[Decimal] = attr(default=None)
     undefined: Optional[bool] = attr(default=False)



class Payment(Entity, tag="payment"): # Abstract base in XSD
    """kursliste:payment complex type (abstract base)"""
    remark: List[Remark] = element(tag="remark", default_factory=list)
    paymentNumber: Optional[int] = attr(default=None)
    paymentDate: Optional[datetime.date] = attr(default=None)
    currency: CurrencyCode = attr(use="required")
    percent: Optional[Percent] = attr(default=None)
    paymentValue: Optional[Decimal] = attr(default=None)
    exchangeRate: Optional[Decimal] = attr(default=None)
    paymentValueCHF: Optional[Decimal] = attr(default=None)
    withHoldingTax: Optional[bool] = attr(default=False)
    undefined: Optional[bool] = attr(default=False)
    sign: Optional[Annotated[str, StringConstraints(min_length=3, max_length=4)]] = attr(default=None)
    paymentType: Optional[PaymentTypeESTV] = attr(default=PaymentTypeESTV.STANDARD)
    taxEvent: Optional[bool] = attr(default=False)
    variant: Optional[Annotated[int, Field(ge=1, le=99999)]] = attr(default=None)



class PaymentBond(Payment, tag="payment"):
    """kursliste:paymentBond complex type"""
    legend: List[Legend] = element(tag="legend", default_factory=list)
    issueDisagio: Optional[Percent] = attr(default=None)
    redemptionAgio: Optional[Percent] = attr(default=None)


class PaymentCurrencyNote(Payment, tag="payment"):
     """kursliste:paymentCurrencyNote complex type"""
     legend: List[Legend] = element(tag="legend", default_factory=list)


class PaymentDerivative(Payment, tag="payment"):
    """kursliste:paymentDerivative complex type"""
    legend: List[Legend] = element(tag="legend", default_factory=list)
    exDate: Optional[datetime.date] = attr(default=None)
    coupon: Optional[Annotated[str, StringConstraints(min_length=1, max_length=12)]] = attr(default=None)


class PaymentFund(Payment, tag="payment"):
    """kursliste:paymentFund complex type"""
    legend: List[Legend] = element(tag="legend", default_factory=list)
    exDate: Optional[datetime.date] = attr(default=None)
    coupon: Optional[Annotated[str, StringConstraints(min_length=1, max_length=12)]] = attr(default=None)
    capitalGain: Optional[bool] = attr(default=False)
    incomeType: Optional[IncomeType] = attr(default=None)
    deduction: Optional[Decimal] = attr(default=None)
    deductionCHF: Optional[Decimal] = attr(default=None)
    deductionDividend: Optional[Decimal] = attr(default=None)
    deductionDividendCHF: Optional[Decimal] = attr(default=None)
    deductionInterest: Optional[Decimal] = attr(default=None)
    deductionInterestCHF: Optional[Decimal] = attr(default=None)



class PaymentShare(Payment, tag="payment"):
    """kursliste:paymentShare complex type"""
    legend: List[Legend] = element(tag="legend", default_factory=list)
    exDate: Optional[datetime.date] = attr(default=None)
    coupon: Optional[Annotated[str, StringConstraints(min_length=1, max_length=12)]] = attr(default=None)
    gratis: Optional[bool] = attr(default=False)
    portefeuille: Optional[bool] = attr(default=False)
    quantity: Optional[Decimal] = attr(default=None)
    paymentValueTotalCHF: Optional[Decimal] = attr(default=None)
    balanceSheetDate: Optional[datetime.date] = attr(default=None)
    provisionallyConfirmed: Optional[datetime.date] = attr(default=None)



class PaymentInstitution(Entity, tag="payment"): # Different base in XSD
    """kursliste:paymentInstitution complex type"""
    paymentNumber: Optional[int] = attr(default=None)
    paymentDate: Optional[datetime.date] = attr(default=None)
    currency: CurrencyCode = attr(use="required")
    percent: Optional[Percent] = attr(default=None)
    paymentValueTotal: Optional[Decimal] = attr(default=None)
    exchangeRate: Optional[Decimal] = attr(default=None)
    paymentValueTotalCHF: Optional[Decimal] = attr(default=None)
    withHoldingTax: Optional[bool] = attr(default=False)
    undefined: Optional[bool] = attr(default=False)
    sign: Optional[Annotated[str, StringConstraints(min_length=3, max_length=4)]] = attr(default=None)
    paymentType: Optional[PaymentTypeESTV] = attr(default=PaymentTypeESTV.STANDARD)
    taxEvent: Optional[bool] = attr(default=False)
    exDate: Optional[datetime.date] = attr(default=None)
    gratis: Optional[bool] = attr(default=False)
    portefeuille: Optional[bool] = attr(default=False)
    balanceSheetDate: Optional[datetime.date] = attr(default=None)



class Quarterly(Daily, tag="quarterly"):
    """kursliste:quarterly complex type"""
    quarter: int = attr(use="required")
    # This seems to not pass validation even on valid values
    # quarter: Annotated[int, Field(ge=1, le=4)] = attr(use="required")


class Security(Entity, tag="security"): # Abstract base in XSD
    """kursliste:security complex type (abstract base)"""
    remark: List[Remark] = element(tag="remark", default_factory=list)
    valorNumber: Optional[ValorNumber] = attr(default=None)
    isin: Optional[IsinStr] = attr(default=None)
    securityGroup: SecurityGroupESTV = attr(use="required")
    securityType: Optional[SecurityTypeESTV] = attr(default=None)
    securityName: Optional[SecurityNameStr] = attr(default=None)
    securityAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=60)]] = attr(default=None)
    sign: Optional[Annotated[str, StringConstraints(min_length=3, max_length=4)]] = attr(default=None)
    iup: Optional[bool] = attr(default=False)
    bfp: Optional[bool] = attr(default=False)
    validity: Optional[Validity] = attr(default=Validity.DEFINITIVE)
    quoted: Optional[bool] = attr(default=True)
    quantity: Optional[Decimal] = attr(default=None)
    source: Optional[Source] = attr(default=Source.KURSLISTE)
    indefaultDate: Optional[datetime.date] = attr(default=None)
    liquidationDate: Optional[datetime.date] = attr(default=None)
    inactiveDate: Optional[datetime.date] = attr(default=None)



class BondIncrease(Entity, tag="increase"):
    """kursliste:bondIncrease complex type"""
    valorNumber: ValorNumber = attr(use="required")


class Bond(Security, tag="bond"):
    """kursliste:bond complex type"""
    yearend: Optional[Yearend] = element( default=None)
    daily: List[Daily] = element( default_factory=list)
    bondfloor: List[Bondfloor] = element( default_factory=list)
    payment: List[PaymentBond] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    increase: List[BondIncrease] = element( default_factory=list)
    institutionId: int = attr(use="required")
    institutionName: InstitutionNameStr = attr(use="required")
    institutionAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = attr(default=None)
    country: CountryCode = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    issueDate: Optional[datetime.date] = attr(default=None)
    redemptionDate: Optional[datetime.date] = attr(default=None)
    redemptionDateEarly: Optional[datetime.date] = attr(default=None)
    issuePrice: Optional[Percent] = attr(default=None)
    redemptionPrice: Optional[Percent] = attr(default=None)
    redemptionPriceEarly: Optional[Percent] = attr(default=None)
    nominalValue: Decimal = attr(use="required")
    interestRate: Optional[Decimal] = attr(default=None)
    interestType: Optional[InterestType] = attr(default=None)
    classicalBond: Optional[bool] = attr(default=False)
    maturityUnlimited: Optional[bool] = attr(default=False)
    liberalized: Optional[Percent] = attr(default=Decimal("100"))
    accruedInterest: Optional[bool] = attr(default=False)
    issuePriceAverage: Optional[Percent] = attr(default=None)
    redemptionDateNoConversion: Optional[bool] = attr(default=False)
    pureDifferentialFrom: Optional[datetime.date] = attr(default=None)



class CoinBullion(Security, tag="coinBullion"):
    """kursliste:coinBullion complex type"""
    yearend: Optional[Yearend] = element( default=None)
    daily: List[Daily] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    country: Optional[CountryCode] = attr(default=None)
    currency: Optional[CurrencyCode] = attr(default=None)
    weight: Optional[Decimal] = attr(default=None)
    weightUnit: Optional[WeightUnit] = attr(default=None)



class CurrencyNote(Security, tag="currencyNote"):
    """kursliste:currencyNote complex type"""
    yearend: Optional[YearendCurrencyNote] = element( default=None)
    daily: List[Daily] = element( default_factory=list)
    payment: List[PaymentCurrencyNote] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    country: Optional[CountryCode] = attr(default=None)
    currency: CurrencyCode = attr(use="required")
    denomination: int = attr(use="required")
    # For some reason using the field validator here causes a newline to be parsed independently of the input
    # denomination: Annotated[int, Field(ge=1, le=1000)] = attr(use="required")



class Derivative(Security, tag="derivative"):
    """kursliste:derivative complex type"""
    yearend: Optional[Yearend] = element( default=None)
    daily: List[Daily] = element( default_factory=list)
    bondfloor: List[Bondfloor] = element( default_factory=list)
    payment: List[PaymentDerivative] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    institutionId: int = attr(use="required")
    institutionName: InstitutionNameStr = attr(use="required")
    institutionAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = attr(default=None)
    country: CountryCode = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    issueDate: Optional[datetime.date] = attr(default=None)
    redemptionDate: Optional[datetime.date] = attr(default=None)
    redemptionDateEarly: Optional[datetime.date] = attr(default=None)
    issuePrice: Optional[Percent] = attr(default=None)
    redemptionPrice: Optional[Percent] = attr(default=None)
    redemptionPriceEarly: Optional[Percent] = attr(default=None)
    nominalValue: Decimal = attr(use="required")
    interestRate: Optional[Decimal] = attr(default=None)
    interestRateInterest: Optional[Decimal] = attr(default=None)
    interestRateOption: Optional[Decimal] = attr(default=None)
    interestType: Optional[InterestType] = attr(default=None)
    maturityUnlimited: Optional[bool] = attr(default=False)
    pureDifferentialFrom: Optional[datetime.date] = attr(default=None)



class Fund(Security, tag="fund"):
    """kursliste:fund complex type"""
    yearend: Optional[Yearend] = element( default=None)
    daily: List[Daily] = element( default_factory=list)
    payment: List[PaymentFund] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    institutionId: int = attr(use="required")
    institutionName: InstitutionNameStr = attr(use="required")
    institutionAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = attr(default=None)
    country: CountryCode = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    nominalValue: Decimal = attr(use="required")



class LiborSwap(Security, tag="liborSwap"):
    """kursliste:liborSwap complex type"""
    daily: List[Daily] = element( default_factory=list)
    quarterly: List[Quarterly] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    country: Optional[CountryCode] = attr(default=None)
    currency: CurrencyCode = attr(use="required")
    period: str = attr(use="required")


class Share(Security, tag="share"):
    """kursliste:share complex type"""
    yearend: List[YearendGrossNet] = element( default_factory=list)
    daily: List[Daily] = element( default_factory=list)
    payment: List[PaymentShare] = element( default_factory=list)
    legend: List[Legend] = element( default_factory=list)
    institutionId: int = attr(use="required")
    institutionName: InstitutionNameStr = attr(use="required")
    institutionAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = attr(default=None)
    country: CountryCode = attr(use="required")
    currency: CurrencyCode = attr(use="required")
    nominalValue: Optional[Decimal] = attr(default=None)
    liberalized: Optional[Percent] = attr(default=Decimal("100"))
    gratis: Optional[bool] = attr(default=False)
    capitalKey: Optional[Annotated[int, Field(ge=1110, le=9959)]] = attr(default=None)
    valorNumberUnderlying: Optional[ValorNumber] = attr(default=None)
    ratioUnderlying: Optional[Decimal] = attr(default=None)
    quotedDate: Optional[datetime.date] = attr(default=None)
    nonQuotedDate: Optional[datetime.date] = attr(default=None)
    tid: Optional[TidType] = attr(default=None)



class CapitalContribution(Entity, tag="capitalContribution"):
    """kursliste:capitalContribution complex type"""
    referenceDate: datetime.date = attr(use="required")
    currency: Optional[CurrencyCode] = attr(default="CHF")
    openingBalance: Optional[Decimal] = attr(default=None)
    closingBalance: Optional[Decimal] = attr(default=None)
    deposit: Optional[Decimal] = attr(default=None)
    repayment: Optional[Decimal] = attr(default=None)
    status: Optional[CapitalContributionStatus] = attr(default=None)



class Institution(Entity, tag="institution"):
    """kursliste:institution complex type"""
    yearend: Optional[YearendInstitution] = element( default=None)
    payment: List[PaymentInstitution] = element( default_factory=list)
    capitalContribution: List[CapitalContribution] = element( default_factory=list)
    remark: List[Remark] = element(tag="remark", default_factory=list)
    uid: Optional[UidStr] = attr(default=None)
    institutionName: InstitutionNameStr = attr(use="required")
    institutionAppendix: Optional[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = attr(default=None)
    additionalPart: Optional[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = attr(default=None)
    street: Optional[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = attr(default=None)
    zip: Optional[Annotated[str, StringConstraints(min_length=1, max_length=12)]] = attr(default=None)
    city: Optional[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = attr(default=None)
    canton: Optional[CantonBFS] = attr(default=None)
    country: CountryCode = attr(use="required")
    municipalNumber: Optional[Annotated[int, Field(ge=1, le=9999)]] = attr(default=None)
    currency: Optional[CurrencyCode] = attr(default=None)
    domain: Optional[Annotated[str, StringConstraints(pattern=r"[A-Za-z0-9._-]+\.[A-Za-z]{2,4}")]] = attr(default=None)
    legalForm: Optional[LegalFormBUR] = attr(default=None)
    sector: Optional[SectorISIC] = attr(default=None)
    institutionNameOld: Optional[InstitutionNameStr] = attr(default=None)
    dossierNumber: Optional[int] = attr(default=None)
    valuationCanton: Optional[CantonBFS] = attr(default=None)
    mandatoryRegistration: Optional[bool] = attr(default=False)
    balanceSheetDate: Optional[str] = attr(default=None)
    source: Optional[Source] = attr(default=Source.KURSLISTE)
    estvId: Optional[Annotated[str, StringConstraints(max_length=80)]] = attr(default=None)
    subsidiary: Optional[bool] = attr(default=False)
    parentUid: Optional[UidStr] = attr(default=None)
    taxExempt: Optional[bool] = attr(default=False)
    totalCapital: Optional[Decimal] = attr(default=None)
    totalCapitalShares: Optional[Decimal] = attr(default=None)
    totalLiberalizedCapital: Optional[Decimal] = attr(default=None)
    totalVotingCapital: Optional[Decimal] = attr(default=None)
    totalPartReceiptCapital: Optional[Decimal] = attr(default=None)



# --- Definition Types ---

class Canton(Entity, tag="canton", nsmap=NSMAP):
    """kursliste:canton complex type"""
    cantonName: List[LangName] = element()
    canton: CantonBFS = attr(use="required")

class CapitalKeyDescription(Entity, tag="capitalKey", nsmap=NSMAP):
    """kursliste:capitalKey complex type"""
    capitalKeyName: List[LangName] = element()
    capitalKey: int = attr(use="required")
    # For some reason usign the field validator here causes a newline to be parsed independently of the input
    # capitalKey: Annotated[int, Field(ge=1110, le=9959)] = attr(use="required")


class Country(Entity, tag="country"):
    """kursliste:country complex type"""
    countryName: List[LangName] = element()
    country: CountryCode = attr(use="required")
    currency: Optional[CurrencyCode] = attr(default=None)

class DefinitionCurrency(Entity, tag="currency"):
    """kursliste:currency complex type"""
    currencyName: List[LangName] = element()
    currency: CurrencyCode = attr(use="required")

class DefinitionSecurityGroup(Entity, tag="securityGroup"):
    """kursliste:securityGroup complex type"""
    securityGroupName: List[LangName] = element()
    securityGroup: SecurityGroupESTV = attr(use="required")

class DefinitionSecurityType(Entity, tag="securityType"):
    """kursliste:securityType complex type"""
    securityTypeName: List[LangName] = element()
    securityType: SecurityTypeESTV = attr(use="required")

class DefinitionLegalForm(Entity, tag="legalForm"):
    """kursliste:legalForm complex type"""
    legalFormName: List[LangName] = element()
    legalForm: LegalFormBUR = attr(use="required")

class Sector(Entity, tag="sector"):
    """kursliste:sector complex type"""
    sectorName: List[LangName] = element()
    sector: SectorISIC = attr(use="required")

class ShortCut(Entity, tag="shortCut"):
    """kursliste:shortCut complex type"""
    shortCutName: List[LangName] = element()
    shortCut: Annotated[str, StringConstraints(min_length=1, max_length=5)] = attr(use="required")

class Sign(Entity, tag="sign"):
    """kursliste:sign complex type"""
    signName: List[LangName] = element()
    sign: Annotated[str, StringConstraints(min_length=3, max_length=4)] = attr(use="required")

class Da1Rate(Entity, tag="da1Rate", nsmap=NSMAP):
    """kursliste:da1Rate complex type"""
    country: CountryCode = attr(use="required")
    securityGroup: SecurityGroupESTV = attr(use="required")
    securityType: Optional[SecurityTypeESTV] = attr(default=None)
    da1RateType: Optional[Da1RateType] = attr(default=Da1RateType.OTHER)
    validFrom: Optional[datetime.date] = attr(default=None)
    validTo: Optional[datetime.date] = attr(default=None)
    value: Percent = attr()
    release: Percent = attr()
    nonRecoverable: Percent = attr()


class MediumTermBond(Entity, tag="mediumTermBond"):
    """kursliste:mediumTermBond complex type"""
    maturityFrom: datetime.date = attr(use="required")
    maturityTo: datetime.date = attr(use="required")
    interestRate: Percent = attr(use="required")
    andHigher: Optional[bool] = attr(default=None)
    price: Percent = attr(use="required")



class ExchangeRate(PydanticXmlModel, tag="exchangeRate"): # Not an Entity
    """kursliste:exchangeRate complex type"""
    currency: CurrencyCode = attr(use="required")
    date: datetime.date = attr(use="required")
    denomination: Optional[Annotated[int, Field(ge=1, le=1000)]] = attr(default=1)
    value: Optional[Decimal] = attr(default=None)



class ExchangeRateMonthly(PydanticXmlModel, tag="exchangeRateMonthly"): # Not an Entity
    """kursliste:exchangeRateMonthly complex type"""
    currency: CurrencyCode = attr(use="required")
    year: int = attr(use="required")
    month: Annotated[str, StringConstraints(pattern=r"0[1-9]|1[0-2]")] = attr(use="required")
    denomination: Optional[Annotated[int, Field(ge=1, le=1000)]] = attr(default=1)
    value: Optional[Decimal] = attr(default=None)



class ExchangeRateYearEnd(PydanticXmlModel, tag="exchangeRateYearEnd"): # Not an Entity
    """kursliste:exchangeRateYearEnd complex type"""
    currency: CurrencyCode = attr(use="required")
    year: int = attr(use="required")
    denomination: Optional[Annotated[int, Field(ge=1, le=1000)]] = attr(default=1)
    value: Optional[Decimal] = attr(default=None)
    valueMiddle: Optional[Decimal] = attr(default=None)



# --- Main Kursliste Model ---

class Kursliste(PydanticXmlModel, tag="kursliste", nsmap=NSMAP):
    """
    Model for the Swiss "Kursliste" (price list) based on kursliste-2.0.0.xsd.
    Reflects the XSD structure with separate lists for definitions and security types.
    """

    # --- Attributes aligned with XSD ---
    version: Annotated[str, StringConstraints(pattern=r"2\.0\.0\.\d")] = attr()
    creationDate: datetime.datetime = attr()
    referingToDate: Optional[datetime.date] = attr(default=None)
    year: int = attr()
    # --- End Attributes ---

    # Pydantic-XML does not know how to ignore meta-attributes like this
    schemaLocation: Optional[str] = attr(
        name="schemaLocation",  # The actual attribute name
        ns='xsi',              # The namespace URI for xsi
        default=None            # Make it optional
    )
    
    # --- Elements based on XSD Sequence ---
    cantons: List[Canton] = element(tag="canton", default_factory=list)
    capitalKeys: List[CapitalKeyDescription] = element(tag="capitalKey", default_factory=list)
    countries: List[Country] = element(tag="country", default_factory=list)
    currencies: List[DefinitionCurrency] = element(tag="currency", default_factory=list)
    securityGroups: List[DefinitionSecurityGroup] = element(tag="securityGroup", default_factory=list)
    securityTypes: List[DefinitionSecurityType] = element(tag="securityType", default_factory=list)
    legalForms: List[DefinitionLegalForm] = element(tag="legalForm", default_factory=list)
    sectors: List[Sector] = element(tag="sector", default_factory=list)
    shortCuts: List[ShortCut] = element(tag="shortCut", default_factory=list)
    signs: List[Sign] = element(tag="sign", default_factory=list)
    da1Rates: List[Da1Rate] = element(tag="da1Rate", default_factory=list)
    mediumTermBonds: List[MediumTermBond] = element(tag="mediumTermBond", default_factory=list)

    institutions: List[Institution] = element(tag="institution", default_factory=list)
    bonds: List[Bond] = element(tag="bond", default_factory=list)
    coinBullions: List[CoinBullion] = element(tag="coinBullion", default_factory=list)
    currencyNotes: List[CurrencyNote] = element(tag="currencyNote", default_factory=list)
    derivatives: List[Derivative] = element(tag="derivative", default_factory=list)
    funds: List[Fund] = element(tag="fund", default_factory=list)
    liborSwaps: List[LiborSwap] = element(tag="liborSwap", default_factory=list)
    shares: List[Share] = element(tag="share", default_factory=list)
    exchangeRates: List[ExchangeRate] = element(tag="exchangeRate", default_factory=list)
    exchangeRatesMonthly: List[ExchangeRateMonthly] = element(tag="exchangeRateMonthly", default_factory=list)
    exchangeRatesYearEnd: List[ExchangeRateYearEnd] = element(tag="exchangeRateYearEnd", default_factory=list)
    # --- End Elements ---

    model_config = ConfigDict(
        validate_assignment=False,
        # extra="forbid"
    )



    # Save memory tim by handling only common types while we have our in memory representation
    DEFAULT_DENYLIST: ClassVar[Set[str]] = {
        "canton",
        "capitalKey",
        "country",
        # "currency", 
        "securityGroup",
        "securityType",
        "legalForm",
        "sector", 
        "shortCut",
        "sign",
        "da1Rate",
        "mediumTermBond",
        "institution",
        "bond",
        "coinBullion",
        "currencyNote", 
        "derivative",
        # "fund",
        "liborSwap",
        # "share",
        # "exchangeRate",
        # "exchangeRateMonthly",
        # "exchangeRateYearEnd"
    }
    
    @staticmethod
    def _filter_xml_elements(root: ET.Element, denylist: Set[str]) -> ET.Element:
        """
        Filter out elements from the XML tree based on the denylist.
        
        Args:
            root: The root XML element
            denylist: Set of element tag names to remove
            
        Returns:
            The filtered XML element tree
        """
        # Modify the tree in place to keep source line annotations
        # (otherwise pydantic-xml's error reporting fails).

        to_remove = []
        # Copy only the elements that are not in the denylist
        for child in root:
            if isinstance(child, ET._Comment):
                continue
            tag = child.tag
            # Remove namespace prefix if present
            if "}" in tag:
                tag = tag.split("}")[1]

            if tag in denylist:
                to_remove.append(child)

        # If denylist is empty, no elements should be removed.
        # If denylist is not empty but no elements match, that's also fine (nothing to remove).
        # The original error for "No elements to remove" when to_remove is empty is problematic
        # if the denylist itself was non-empty but simply didn't match any children.
        # A more critical check is if denylist is non-empty AND to_remove is empty,
        # indicating a possible misconfiguration of the denylist.
        # However, for the case where denylist=set() is passed to load everything,
        # to_remove will be empty, and we should not raise an error.

        if not to_remove: # Covers empty denylist or non-empty denylist with no matches
            # If denylist was non-empty and to_remove is empty, it means no listed elements were found.
            # This is not necessarily an error; it could be that the XML doesn't contain those elements.
            # If denylist was empty, this is the correct path.
            # print(f"No elements matching denylist found to remove, or denylist was empty.")
            pass # Proceed without removing anything
        else:
            for child in to_remove:
                root.remove(child)
            print(f"Filtered {len(to_remove)} elements based on denylist.")
            
        return root
    
    @classmethod
    def from_xml_file(cls, file_path: Union[str, Path], denylist: Optional[Set[str]] = None) -> "Kursliste":
        """
        Load a Kursliste from an XML file using raw bytes.
        
        Args:
            file_path: Path to the XML file
            denylist: Optional set of element names to exclude from parsing.
                      If None, uses DEFAULT_DENYLIST.
        
        Returns:
            Kursliste instance
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)

        if not file_path.is_file():
            raise FileNotFoundError(f"XML file not found at path: {file_path}")

        try:
            
            # Parse the XML first to filter elements
            root = ET.parse(file_path).getroot()
            
            # Use the default denylist if none provided
            if denylist is None:
                denylist = cls.DEFAULT_DENYLIST
                
            filtered_root = cls._filter_xml_elements(root, denylist)

            instance = cls.from_xml_tree(filtered_root)
            return instance
        except ET.ParseError as e:
            raise ValueError(f"XML parsing error in file {file_path}: {e}") from e
        except ValidationError as e:
             print(f"Pydantic Validation Errors:\n{e}")
             raise ValueError(f"Data validation error loading XML file {file_path}: {e}") from e
        except Exception as e:
            raise RuntimeError(f"An unexpected error occurred while processing {file_path}: {e}") from e

    def find_security_by_valor(self, valor_number: int) -> Optional[Security]:
        """
        Find a security by its valor number.
        
        Args:
            valor_number: The valor number to search for
            
        Returns:
            The security if found, None otherwise
        """
        # Search in all security types
        # TODO this does not handle special issues etc, that are subelemts
        for security_list in [
            self.bonds, 
            self.shares, 
            self.funds, 
            self.derivatives, 
            self.coinBullions, 
            self.currencyNotes, 
            self.liborSwaps
        ]:
            for security in security_list:
                if security.valorNumber == valor_number:
                    return security
        return None
    
    def find_security_by_isin(self, isin: str) -> Optional[Security]:
        """
        Find a security by its ISIN.
        
        Args:
            isin: The ISIN to search for
            
        Returns:
            The security if found, None otherwise
        """
        # Search in all security types
        for security_list in [
            self.bonds, 
            self.shares, 
            self.funds, 
            self.derivatives, 
            self.coinBullions, 
            self.currencyNotes, 
            self.liborSwaps
        ]:
            for security in security_list:
                if security.isin == isin:
                    return security
        return None
    
    def find_securities_by_valor(self, valor_number: int) -> List[Security]:
        """
        Find all securities with the given valor number.
        
        Args:
            valor_number: The valor number to search for
            
        Returns:
            List of securities with the matching valor number
        """
        results = []
        for security_list in [
            self.bonds, 
            self.shares, 
            self.funds, 
            self.derivatives, 
            self.coinBullions, 
            self.currencyNotes, 
            self.liborSwaps
        ]:
            for security in security_list:
                if security.valorNumber == valor_number:
                    results.append(security)
        return results
    
    def find_securities_by_isin(self, isin: str) -> List[Security]:
        """
        Find all securities with the given ISIN.
        
        Args:
            isin: The ISIN to search for
            
        Returns:
            List of securities with the matching ISIN
        """
        results = []
        for security_list in [
            self.bonds, 
            self.shares, 
            self.funds, 
            self.derivatives, 
            self.coinBullions, 
            self.currencyNotes, 
            self.liborSwaps
        ]:
            for security in security_list:
                if security.isin == isin:
                    results.append(security)
        return results


