import json

def extract_values(obj, key):
    """
    Recursively fetch values from nested JSON by key name.
    
    :param obj: The JSON object (dict or list)
    :param key: The key you want to extract
    :return: A list of values found for the given key
    """
    values = []

    def _extract(obj, values, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key:
                    values.append(v)
                if isinstance(v, (dict, list)):
                    _extract(v, values, key)
        elif isinstance(obj, list):
            for item in obj:
                _extract(item, values, key)
        return values

    results = _extract(obj, values, key)
    return results



# data = {'transportDocumentReference': '255553918', 'carrierCodeListProvider': 'NMFTA', 'issuingParty': {'partyName': 'Maersk South Africa (CPT)', 'partyContactDetails': [{'name': 'Company Contact'}], 'identifyingCodes': [{'partyCode': 'ZACPTMSL1', 'codeListName': 'maerskIssueAgentCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}]}, 'shippingInstruction': {'shippingInstructionReference': '255553918', 'documentStatus': 'RECE', 'shippingInstructionCreatedDateTime': '2025-06-24T09:16:42Z', 'isElectronic': False, 'isToOrder': False, 'isShippedOnBoardType': True, 'consignmentItems': [{'carrierBookingReference': '254025709', 'weight': 56540.0, 'volume': 74.35, 'weightUnit': 'KGM', 'volumeUnit': 'MTQ', 'descriptionOfGoods': 'CCA H2 TREATED KILN DRIED SA PINE TIMBER', 'cargoItems': [{'equipmentReference': 'HASU4628943', 'weight': 28260.0, 'volume': 38.232, 'weightUnit': 'KGM', 'volumeUnit': 'MTQ', 'numberOfPackages': 16, 'packageCode': 'BE', 'packageNameOnBL': 'BUNDLES'}, {'equipmentReference': 'MRSU5372917', 'weight': 28280.0, 'volume': 36.118, 'weightUnit': 'KGM', 'volumeUnit': 'MTQ', 'numberOfPackages': 13, 'packageCode': 'BE', 'packageNameOnBL': 'BUNDLES'}], 'HSCode': '440711'}], 'utilizedTransportEquipments': [{'equipment': {'equipmentReference': 'HASU4628943', 'ISOEquipmentCode': '45G0'}, 'cargoGrossWeight': 28260.0, 'cargoGrossWeightUnit': 'KGM', 'cargoGrossVolume': 38.232, 'cargoGrossVolumeUnit': 'MTQ', 'numberOfPackages': 16, 'isShipperOwned': False, 'seals': [{'sealNumber': 'ZA6497691', 'sealSource': 'CAR', 'sealType': 'BLT'}]}, {'equipment': {'equipmentReference': 'MRSU5372917', 'ISOEquipmentCode': '45G0'}, 'cargoGrossWeight': 28280.0, 'cargoGrossWeightUnit': 'KGM', 'cargoGrossVolume': 36.118, 'cargoGrossVolumeUnit': 'MTQ', 'numberOfPackages': 13, 'isShipperOwned': False, 'seals': [{'sealNumber': 'ZA6497685', 'sealSource': 'CAR', 'sealType': 'BLT'}]}], 'transportDocumentTypeCode': 'SWB', 'numberOfOriginalsWithoutCharges': 1, 'displayedNameForPortOfLoad': ['Durban'], 'displayedNameForPortOfDischarge': ['Victoria'], 'carrierBookingReference': '254025709', 'placeOfIssue': {'locationName': 'Cape Town', 'UNLocationCode': 'ZACPT'}, 'documentParties': [{'party': {'partyName': 'TNS FREIGHT CONSOLIDATION', 'taxReference1': '4770256958', 'address': {'streetName': '', 'cityName': 'DURBAN', 'streetNumber': ' ', 'postCode': '4000', 'stateRegion': 'NL', 'country': 'South Africa'}, 'partyContactDetails': [{'name': 'Company Contact', 'phone': ' ', 'email': 'naz@tnsfreightcon.co.za'}], 'identifyingCodes': [{'partyCode': '24000173789', 'codeListName': 'maerskCustomerCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}], 'displayedAddresses': [{'addressLine': ' '}]}, 'partyFunction': 'BA'}, {'party': {'partyName': 'SOUTH SEAS IMPORT EXPORT CC', 'taxReference1': ' ', 'address': {'streetName': 'REGENT ROAD', 'cityName': 'CAPE TOWN', 'streetNumber': '13', 'postCode': '8005', 'stateRegion': 'WC', 'country': 'South Africa'}, 'partyContactDetails': [{'name': 'Company Contact', 'phone': ' ', 'email': 'darryn.aitken@southseasimpex.com'}], 'identifyingCodes': [{'partyCode': '24000784665', 'codeListName': 'maerskCustomerCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}], 'displayedAddresses': [{'addressLine': ' '}]}, 'partyFunction': 'SCO'}, {'party': {'partyName': 'P&J SUPPLIES (PTE) LTD', 'taxReference1': 'LLL371288530', 'address': {'streetName': 'PROVIDENCE INDUSTRIAL ESTATE', 'cityName': 'VICTORIA', 'streetNumber': ' ', 'stateRegion': ' ', 'country': 'Seychelles'}, 'partyContactDetails': [{'name': 'Company Contact', 'phone': ' ', 'email': 'pnjsupplies@seychelles.net'}], 'identifyingCodes': [{'partyCode': '254000557', 'codeListName': 'maerskCustomerCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}], 'displayedAddresses': [{'addressLine': 'PNJ SUPPLIES\r\nPROVIDENCE INDUSTRIAL ESTATE\r\nPO BOX 25\r\nSEYCHELLES'}]}, 'partyFunction': 'N1'}, {'party': {'partyName': 'SOUTH SEAS IMPORT EXPORT CC', 'taxReference1': ' ', 'address': {'streetName': 'REGENT ROAD', 'cityName': 'CAPE TOWN', 'streetNumber': '13', 'postCode': '8005', 'stateRegion': 'WC', 'country': 'South Africa'}, 'partyContactDetails': [{'name': 'Company Contact', 'phone': ' ', 'email': 'darryn.aitken@southseasimpex.com'}], 'identifyingCodes': [{'partyCode': '24000784665', 'codeListName': 'maerskCustomerCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}], 'displayedAddresses': [{'addressLine': 'South Seas Import/Export (PTY) LTD \r\n22 OLD MILL ROAD\r\nNDABENI, 7405\r\nCape Town,South Africa'}]}, 'partyFunction': 'OS'}, {'party': {'partyName': 'P&J SUPPLIES (PTE) LTD', 'taxReference1': 'LLL371288530', 'address': {'streetName': 'PROVIDENCE INDUSTRIAL ESTATE', 'cityName': 'VICTORIA', 'streetNumber': ' ', 'stateRegion': ' ', 'country': 'Seychelles'}, 'partyContactDetails': [{'name': 'Company Contact', 'phone': ' ', 'email': 'pnjsupplies@seychelles.net'}], 'identifyingCodes': [{'partyCode': '254000557', 'codeListName': 'maerskCustomerCode', 'DCSAResponsibleAgencyCode': 'ZZZ'}], 'displayedAddresses': [{'addressLine': 'PNJ SUPPLIES\r\nPROVIDENCE INDUSTRIAL ESTATE\r\nPO BOX 25\r\nSEYCHELLES'}]}, 'partyFunction': 'CN'}], 'references': []}, 'transportDocumentCreatedDateTime': '2025-06-23T12:58:11Z', 'transportDocumentUpdatedDateTime': '2025-07-15T19:48:29Z', 'issueDate': '2025-07-08', 'shippedOnBoardDate': '2025-06-28', 'receivedForShipmentDate': '2025-06-22', 'receiptTypeAtOrigin': 'CY', 'deliveryTypeAtDestination': 'CY', 'cargoMovementTypeAtOrigin': 'FCL', 'cargoMovementTypeAtDestination': 'FCL', 'serviceContractReference': '299264197', 'vesselName': 'CEZANNE', 'carrierExportVoyageNumber': '526N', 'transports': [{'transportPlanStage': 'MNC', 'transportPlanStageSequenceNumber': 1, 'loadLocation': {'locationName': 'Durban, Container Terminal', 'UNLocationCode': 'ZADUR'}, 'dischargeLocation': {'locationName': 'Port Louis Terminal', 'UNLocationCode': 'MUPLU'}, 'plannedDepartureDate': '2025-06-28', 'plannedArrivalDate': '2025-07-05', 'modeOfTransport': 'VESSEL', 'vesselName': 'CEZANNE', 'vesselIMONumber': '9697416', 'carrierImportVoyageNumber': ' ', 'carrierExportVoyageNumber': '526N', 'isUnderShippersResponsibility': False}, {'transportPlanStage': 'MNC', 'transportPlanStageSequenceNumber': 2, 'loadLocation': {'locationName': 'Port Louis Terminal', 'UNLocationCode': 'MUPLU'}, 'dischargeLocation': {'locationName': 'Victoria Port Terminal', 'UNLocationCode': 'SCVIC'}, 'plannedDepartureDate': '2025-07-11', 'plannedArrivalDate': '2025-07-16', 'modeOfTransport': 'VESSEL', 'vesselName': 'MERATUS JAYAWIJAYA', 'vesselIMONumber': '9305881', 'carrierImportVoyageNumber': ' ', 'carrierExportVoyageNumber': '527N', 'isUnderShippersResponsibility': False}], 'shipmentLocations': [{'shipmentLocationTypeCode': 'PRE', 'eventDateTime': '2025-06-28T22:00:00Z', 'location': {'locationName': 'Durban, Container Terminal', 'UNLocationCode': 'ZADUR'}}, {'shipmentLocationTypeCode': 'POL', 'eventDateTime': '2025-06-28T22:00:00Z', 'location': {'locationName': 'Durban, Container Terminal', 'UNLocationCode': 'ZADUR'}}, {'shipmentLocationTypeCode': 'POD', 'eventDateTime': '2025-07-16T04:00:00Z', 'location': {'locationName': 'Victoria Port Terminal', 'UNLocationCode': 'SCVIC'}}, {'shipmentLocationTypeCode': 'PDE', 'eventDateTime': '2025-07-16T04:00:00Z', 'location': {'locationName': 'Victoria Port Terminal', 'UNLocationCode': 'SCVIC'}}], 'placeOfIssue': {'locationName': 'Cape Town', 'UNLocationCode': 'ZACPT'}}

# Extract examples
# print("All partyName:", extract_values(data, "equipmentReference"))
# print("All weight:", extract_values(data, "weight"))
# print("All carrierBookingReference:", extract_values(data, "carrierBookingReference"))


# import ast

# def format_python_dict_file(input_file_path, output_file_path, indent=2):
#     """
#     For files containing Python dictionary syntax (like your example).
#     """
#     try:
#         # Read the content from input file
#         with open(input_file_path, 'r', encoding='utf-8') as input_file:
#             content = input_file.read()
        
#         # Convert Python dict string to actual dictionary using ast.literal_eval
#         data_dict = ast.literal_eval(content)
        
#         # Convert to JSON and write with proper indentation
#         with open(output_file_path, 'w', encoding='utf-8') as output_file:
#             json.dump(data_dict, output_file, indent=indent, ensure_ascii=False)
        
#         print(f"Successfully formatted and saved to {output_file_path}")
        
#     except (SyntaxError, ValueError) as e:
#         print(f"Error parsing the dictionary: {e}")
#     except Exception as e:
#         print(f"An error occurred: {e}")

# # Usage for your specific case
# format_python_dict_file("output.txt", "formatted_output.json")
