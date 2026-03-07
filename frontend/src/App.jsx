import React from 'react';
import Dashboard from './components/Dashboard';
import { BetSlipProvider } from './context/BetSlipContext';
import BetSlipSidebar from './components/BetSlipSidebar';

function App() {
  return (
    <BetSlipProvider>
      <div className="flex flex-col lg:flex-row min-h-screen bg-slate-950">
        <div className="flex-1 w-full">
          <Dashboard />
        </div>
        <BetSlipSidebar />
      </div>
    </BetSlipProvider>
  );
}

export default App;
