import React, { useState, useEffect } from 'react';
import { X, Trophy, Trash2, Send, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import axios from 'axios';
import { useBetSlip } from '../context/BetSlipContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const BetSlipSidebar = () => {
    const { betSlip, removeFromSlip, clearSlip } = useBetSlip();
    const [isAdmin, setIsAdmin] = useState(false);
    const [isSharing, setIsSharing] = useState(false);
    const [shareMessage, setShareMessage] = useState(null);
    const [isMinimized, setIsMinimized] = useState(() => betSlip.length > 0);

    // Check for admin token on mount
    useEffect(() => {
        const token = localStorage.getItem('token');
        if (token) {
            try {
                // ... (Decode logic remains exactly the same)
                const base64Url = token.split('.')[1];
                const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
                const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
                    return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
                }).join(''));

                const payload = JSON.parse(jsonPayload);
                if (payload.role === 'admin') {
                    setIsAdmin(true);
                }
            } catch (e) {
                console.error("Failed to decode token", e);
            }
        }
    }, [betSlip.length]);

    const handleShareTelegram = async () => {
        if (betSlip.length === 0) return;

        setIsSharing(true);
        setShareMessage(null);

        try {
            const token = localStorage.getItem('token');
            const response = await axios.post(`${API_URL}/share-betslip`,
                { bets: betSlip },
                { headers: { Authorization: `Bearer ${token}` } }
            );

            setShareMessage({ type: 'success', text: 'Shared to Telegram!' });

            // Clear message after 3 seconds
            setTimeout(() => setShareMessage(null), 3000);
        } catch (err) {
            console.error(err);
            setShareMessage({
                type: 'error',
                text: err.response?.data?.detail || 'Failed to share to Telegram'
            });
            setTimeout(() => setShareMessage(null), 4000);
        } finally {
            setIsSharing(false);
        }
    };

    if (betSlip.length === 0) {
        return null; // Empty state
    }

    if (isMinimized) {
        return (
            <button
                onClick={() => setIsMinimized(false)}
                className="fixed bottom-6 right-6 bg-gray-900 border border-purple-500 shadow-2xl shadow-purple-900/20 z-50 rounded-full px-6 py-3 flex items-center justify-center gap-3 animate-bounce hover:bg-gray-800 transition-colors"
            >
                <div className="relative">
                    <Trophy className="w-6 h-6 text-yellow-500" />
                    <span className="absolute -top-2 -right-2 bg-blue-600 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
                        {betSlip.length}
                    </span>
                </div>
                <span className="font-bold text-white">View Bet Slip</span>
                <ChevronUp className="w-5 h-5 text-gray-400" />
            </button>
        );
    }

    // Calculate total odds (simple multiplier)
    const totalOdds = betSlip.reduce((acc, bet) => acc * (bet.odds || 1.0), 1.0).toFixed(2);
    const potentialReturn = (10 * totalOdds).toFixed(2); // Assuming $10 stake unit

    return (
        <div className="fixed right-0 top-0 h-full w-80 bg-gray-900 border-l border-gray-800 shadow-2xl z-50 flex flex-col animate-slideLeft">
            <div className="p-4 border-b border-gray-800 bg-gray-800/50 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                        <Trophy className="w-5 h-5 text-yellow-500" /> Bet Slip
                    </h2>
                    <span className="bg-blue-600 text-xs text-white rounded-full px-2 py-0.5 font-bold">
                        {betSlip.length}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={clearSlip}
                        className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                        title="Clear Slip"
                    >
                        <Trash2 className="w-4 h-4" />
                    </button>
                    <button
                        onClick={() => setIsMinimized(true)}
                        className="p-1.5 text-gray-500 hover:text-white hover:bg-gray-700/50 rounded transition-colors"
                        title="Minimize"
                    >
                        <ChevronDown className="w-5 h-5" />
                    </button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                {betSlip.map((bet) => (
                    <div key={bet.match_id} className="bg-gray-800 rounded-lg p-3 border border-gray-700 relative group">
                        <button
                            onClick={() => removeFromSlip(bet.match_id)}
                            className="absolute top-2 right-2 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                            <X className="w-4 h-4" />
                        </button>
                        <div className="text-xs text-gray-400 mb-1 font-semibold">{bet.match}</div>
                        {bet.match_date && (
                            <div className="text-[10px] text-gray-500 mb-2 font-mono">
                                {new Date(bet.match_date).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                            </div>
                        )}
                        <div className="text-blue-300 font-bold">{bet.selection}</div>
                        <div className="text-xs text-green-400 mt-1 flex justify-between">
                            <span>Safe Bet</span>
                            <span className="font-mono bg-gray-900 px-1 rounded">@{bet.odds}</span>
                        </div>
                    </div>
                ))}
            </div>

            <div className="p-4 border-t border-gray-800 bg-gray-800/30">
                <div className="flex justify-between items-center mb-2 text-sm text-gray-400">
                    <span>Total Odds</span>
                    <span className="text-white font-mono">{totalOdds}</span>
                </div>
                <div className="flex justify-between items-center mb-4 text-sm text-gray-400">
                    <span>Est. Return ($10)</span>
                    <span className="text-green-400 font-bold font-mono">${potentialReturn}</span>
                </div>

                {shareMessage && (
                    <div className={`mb-3 p-2 rounded text-xs text-center border ${shareMessage.type === 'success'
                        ? 'bg-green-500/10 border-green-500/20 text-green-400'
                        : 'bg-red-500/10 border-red-500/20 text-red-500'
                        }`}>
                        {shareMessage.text}
                    </div>
                )}

                <div className="flex flex-col gap-2">
                    {isAdmin && (
                        <button
                            onClick={handleShareTelegram}
                            disabled={isSharing}
                            className="w-full bg-[#0088cc] hover:bg-[#0077b3] text-white font-bold py-3 rounded-lg transition-colors flex items-center justify-center gap-2 shadow-lg shadow-[#0088cc]/20 disabled:opacity-50"
                        >
                            {isSharing ? (
                                <>
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    Sending...
                                </>
                            ) : (
                                <>
                                    <Send className="w-4 h-4" />
                                    Share to Telegram
                                </>
                            )}
                        </button>
                    )}

                    <button className="w-full bg-green-600 hover:bg-green-500 text-white font-bold py-3 rounded-lg transition-colors shadow-lg shadow-green-900/20">
                        Place Bet
                    </button>
                </div>
            </div>
        </div>
    );
};

export default BetSlipSidebar;
