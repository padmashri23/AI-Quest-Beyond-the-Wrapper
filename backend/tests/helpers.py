"""Helpers shared by the API test modules. The signed-in `client` fixture lives in conftest.py."""

PASSWORD = 'test-only-long-password-42'


def inventory(c, description='Natural gas', quantity='100', unit='therm', region='US', jurisdiction='SEC'):
    """Create a one-line inventory through the HTTP API and return the run payload."""
    csv = f'description,quantity,unit,region,period\n{description},{quantity},{unit},{region},FY2025\n'.encode()
    response = c.post('/api/runs', data={'org_name': 'Test Manufacturing', 'jurisdiction': jurisdiction},
                      files=[('files', ('activity.csv', csv, 'text/csv'))])
    assert response.status_code == 200, response.text
    return response.json()
