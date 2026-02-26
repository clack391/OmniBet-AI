import React, { createContext, useContext, useState, useEffect } from 'react';

const BetSlipContext = createContext();

export const useBetSlip = () => useContext(BetSlipContext);

export const BetSlipProvider = ({ children }) => {
    // Initialize from localStorage if available
    const [betSlip, setBetSlip] = useState(() => {
        try {
            const savedSlip = localStorage.getItem('betSlip');
            return savedSlip ? JSON.parse(savedSlip) : [];
        } catch (error) {
            console.error("Failed to parse betslip from localStorage", error);
            return [];
        }
    });

    // Save to localStorage whenever it changes
    useEffect(() => {
        localStorage.setItem('betSlip', JSON.stringify(betSlip));
    }, [betSlip]);

    const addToSlip = (bet) => {
        // Avoid duplicates
        if (!betSlip.some(b => b.match_id === bet.match_id)) {
            setBetSlip([...betSlip, bet]);
        }
    };

    const removeFromSlip = (matchId) => {
        setBetSlip(betSlip.filter(bet => bet.match_id !== matchId));
    };

    const clearSlip = () => {
        setBetSlip([]);
    };

    return (
        <BetSlipContext.Provider value={{ betSlip, addToSlip, removeFromSlip, clearSlip }}>
            {children}
        </BetSlipContext.Provider>
    );
};
