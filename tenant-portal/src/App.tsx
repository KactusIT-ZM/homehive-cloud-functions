import React from 'react';
import './App.css';

function App() {
  const [invoiceUrl, setInvoiceUrl] = React.useState<string | null>(null);

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const url = params.get('invoiceUrl');
    if (url) {
      setInvoiceUrl(url);
    }
  }, []);

  return (
    <div className="App">
      <header className="App-header">
        <img src="/logo.png" className="App-logo" alt="logo" style={{ height: '50px', marginRight: '10px' }} />
        <h1>HomeHive Invoice</h1>
      </header>
      <main>
        {invoiceUrl ? (
          <iframe 
            src={invoiceUrl} 
            width="100%" 
            height="600px" 
            style={{ border: 'none' }} 
            title="Invoice"
          ></iframe>
        ) : (
          <p>No invoice URL provided. Please ensure you access this page via a valid link.</p>
        )}
      </main>
    </div>
  );
}

export default App;
