# Known Specification Issues and Discrepancies

This document tracks known issues and discrepancies between different specifications and standards used in this project.

## eCH-0196 vs Kursliste Specification Discrepancies

### Security Name Length Limits

**Issue**: There is a discrepancy between the maximum allowed length for security names between the eCH-0196 and Kursliste specifications.

**Details**:
- **eCH-0196-2-2.xsd**: `securityNameType` has `maxLength=60`
- **kursliste-2.0.0.xsd**: `securityName` has `maxLength=120`

**Real-world Impact**: 
Real financial data from brokers like IBKR often contains security names that exceed the 60-character limit imposed by eCH-0196 but fall within the 120-character limit of the Kursliste specification.

**Example Case**:
- Security name: `PICTET AM (EUROPE) (LU) PICTET SHORT-TERM MONEY MARKET (CHF) "P" INC`
- Length: 68 characters
- Status: Exceeds eCH-0196 limit (60) but within Kursliste limit (120)

**Resolution**: 
Since eCH-0196 is the target standard and cannot be changed, we implement automatic truncation of security names to fit within the 60-character limit while preserving readability by showing both the beginning and end of the name.

### Implementation

The truncation follows the Pydantic format:
- Preserves characters from the beginning
- Shows `...` in the middle to indicate truncation
- Preserves characters from the end
- Total length including `...` equals exactly 60 characters

**Example**:
```
Original: "PICTET AM (EUROPE) (LU) PICTET SHORT-TERM MONEY MARKET (CHF) "P" INC"
Truncated: "PICTET AM (EUROPE) (LU) PICTET SHORT-T...ET (CHF) "P" INC"
```

## Other Known Issues

### Future Considerations

1. **Currency Code Validation**: Some brokers may use non-standard currency codes that don't match ISO 4217.
2. **Date Format Variations**: Different data sources may use varying date formats that need normalization.
3. **Decimal Precision**: Financial calculations may require specific precision handling beyond standard decimal types.

## Contributing

When encountering new specification discrepancies:

1. Document the issue in this file
2. Provide examples of real-world data that causes the issue
3. Implement a pragmatic solution that maintains compliance with the primary standard (eCH-0196)
4. Add appropriate tests to ensure the solution works correctly 