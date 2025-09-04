import requests
from requests.auth import HTTPBasicAuth
import os
from datetime import datetime

class CMACGMBookingAPI:
    def __init__(self, client_id, client_secret):
        """
        Initialize the API client with OAuth2 credentials
        
        Args:
            client_id (str): OAuth2 client ID
            client_secret (str): OAuth2 client secret
        """
        self.base_url = "https://apis.cma-cgm.net/commercial/shippingdocument/v1"
        self.token_url = "https://auth.cma-cgm.com/as/token.oauth2"
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = None

    def _get_access_token(self):
        """Obtain a new OAuth2 access token using client credentials flow"""
        try:
            auth = HTTPBasicAuth(self.client_id, self.client_secret)
            data = {
                'grant_type': 'client_credentials',
                'scope': 'shippingDocument:loadBKGCF:be'
            }
            
            response = requests.post(self.token_url, auth=auth, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data['access_token']
            # Set expiry with 5 minute buffer (typically tokens expire in 1 hour)
            self.token_expiry = datetime.now().timestamp() + token_data.get('expires_in', 3600) - 300
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"Failed to obtain access token: {str(e)}")
            if hasattr(e, 'response') and e.response:
                print(f"Error details: {e.response.text}")
            return False

    def _check_token_valid(self):
        """Check if current token is still valid"""
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.now().timestamp() < self.token_expiry

    def get_booking_confirmation(self, shipment_id, behalf_of=None, output_dir="downloads"):
        """
        Retrieve booking confirmation PDF for a given shipment ID
        
        Args:
            shipment_id (str): Booking reference number
            behalf_of (str, optional): End customer code if third party
            output_dir (str): Directory to save the PDF file
            
        Returns:
            dict: {
                'success': bool,
                'file_path': str if successful,
                'error': str if failed
            }
        """
        # Ensure we have a valid token
        if not self._check_token_valid() and not self._get_access_token():
            return {
                'success': False,
                'error': 'Authentication failed'
            }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/pdf'
        }

        params = {}
        if behalf_of:
            params['behalfOf'] = behalf_of

        try:
            url = f"{self.base_url}/shipments/{shipment_id}/bookingConfirmation"
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                # Create output directory if it doesn't exist
                os.makedirs(output_dir, exist_ok=True)
                
                # Generate filename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"booking_confirmation_{shipment_id}_{timestamp}.pdf"
                filepath = os.path.join(output_dir, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                return {
                    'success': True,
                    'file_path': filepath,
                    'message': f"Successfully saved booking confirmation to {filepath}"
                }
            
            # Handle error responses
            error_info = self._parse_error_response(response)
            return {
                'success': False,
                'error': error_info['message'],
                'details': error_info['details']
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f"\nResponse: {e.response.text}"
            return {
                'success': False,
                'error': error_msg
            }

    def _parse_error_response(self, response):
        """Parse error response from API"""
        error_map = {
            400: {
                'type': 'Bad Request',
                'codes': {
                    'BKG_ERR': 'Booking unknown'
                }
            },
            403: {
                'type': 'Forbidden',
                'message': 'Not authorized to access this booking confirmation'
            },
            404: {
                'type': 'Not Found',
                'codes': {
                    'CNF_BKG': 'Booking not confirmed yet, please contact your agent',
                    'PDF_BKG': 'Booking confirmation PDF not published yet, please contact your agent'
                }
            },
            500: {
                'type': 'Server Error',
                'message': 'Service unavailable'
            }
        }
        
        status = response.status_code
        error_data = {
            'status': status,
            'type': error_map.get(status, {}).get('type', 'Unknown Error'),
            'message': '',
            'details': {}
        }
        
        try:
            response_json = response.json()
            error_data['details'] = {
                'reason': response_json.get('reason'),
                'code': response_json.get('code'),
                'description': response_json.get('description')
            }
            
            if status == 400 or status == 404:
                code = response_json.get('code')
                if code in error_map[status].get('codes', {}):
                    error_data['message'] = error_map[status]['codes'][code]
                else:
                    error_data['message'] = error_map[status].get('message', 'Unknown error code')
            else:
                error_data['message'] = error_map.get(status, {}).get('message', 'Unknown error')
                
        except ValueError:
            error_data['message'] = error_map.get(status, {}).get('message', 'Unknown error')
            error_data['details']['raw_response'] = response.text
            
        return error_data

# Example usage
if __name__ == "__main__":
    # Configuration - Replace with your actual credentials
    CLIENT_ID = "beapp-fusiontech"
    CLIENT_SECRET = "T3FefGXrLjQBWCQT98D1VsbKXb1aKGgOWamRUSGWkDmvlNzR1ZsLv0El8XF7RDFS"
    SHIPMENT_ID = "MG/CT/2003"  # Example: "BKG12345678"
    BEHALF_OF = None  # Set if you're a third party
    
    # Initialize API client
    api = CMACGMBookingAPI(CLIENT_ID, CLIENT_SECRET)
    
    # Get booking confirmation
    result = api.get_booking_confirmation(
        shipment_id=SHIPMENT_ID,
        behalf_of=BEHALF_OF,
        output_dir="./booking_downloads"
    )
    
    # Handle results
    if result['success']:
        print("Success:", result['message'])
        print("File saved at:", result['file_path'])
    else:
        print("Error:", result['error'])
        if 'details' in result:
            print("Error details:", result['details'])