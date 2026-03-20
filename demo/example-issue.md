### Application Name

Payment Gateway v2

### Business Unit

Platform Engineering

### Source Zone / Network

web-zone

### Destination Zone / Network

app-zone

### Required Ports / Services

TCP/443 (HTTPS)

### Business Justification

The Payment Gateway v2 service requires a new firewall rule to allow HTTPS traffic from the web-facing tier (web-zone) to the application tier (app-zone) on port 443. This change is required to meet PCI-DSS compliance obligations for the new payment processing service. The service handles card-holder data and must communicate over encrypted HTTPS connections with the application backend. An existing payment processor integration is being migrated from a legacy system; the new architecture separates the web presentation layer from the payment processing logic to reduce PCI-DSS scope. This rule enables that separation while maintaining the principle of least privilege — only TCP/443 is permitted, and only between the designated zones.

### Supporting Documentation

No attachments — demo mode.
