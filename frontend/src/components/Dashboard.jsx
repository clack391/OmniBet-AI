import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Calendar, CheckCircle, Search, Trophy, AlertCircle, Loader2, Zap } from 'lucide-react';
import PredictionCard from './PredictionCard';
import HistoryTab from './HistoryTab';
import { useBetSlip } from '../context/BetSlipContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const Dashboard = () => {
    const { addToSlip } = useBetSlip();
    const [date, setDate] = useState('');
    const [fixtures, setFixtures] = useState([]);
    const [selectedMatches, setSelectedMatches] = useState([]); // Now stores full match objects: { id, homeTeam, awayTeam }
    const [loadingFixtures, setLoadingFixtures] = useState(false);
    const [analyzing, setAnalyzing] = useState(false);
    const [predictions, setPredictions] = useState([]);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('calendar');

    const handleSelectHistoryItem = (item) => {
        // The backend now returns the fully hydrated Prediction object exactly as it was generated
        // (including logos, risk manager reasoning, etc.) from the SQLite database.

        // Load it directly into the main view
        setPredictions([item]);

        // Jump back to the Calendar tab to view it
        setActiveTab('calendar');

        // Scroll to top to ensure they see it if they were far down the history list
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Fetch fixtures when date changes
    useEffect(() => {
        if (date) {
            fetchFixtures();
        }
    }, [date]);

    const fetchFixtures = async () => {
        setLoadingFixtures(true);
        setFixtures([]);
        setError(null);
        try {
            // WORKAROUND: The API seems to treat dateTo specifically (or has data issues). 
            // We fetch a 2-day range (selected date and next day) to ensure we capture all matches 
            // for the selected date, then filter client-side.
            const currentDateObj = new Date(date);
            const nextDateObj = new Date(currentDateObj);
            nextDateObj.setDate(currentDateObj.getDate() + 1);
            const nextDate = nextDateObj.toISOString().split('T')[0];

            const response = await axios.get(`${API_URL}/fixtures`, {
                params: {
                    start_date: date,
                    end_date: nextDate
                }
            });

            // Filter matches to only include those strictly on the selected 'date' (ignoring time)
            // Note: date input is YYYY-MM-DD. match.utcDate is ISO string.
            // We compare YYYY-MM-DD parts.
            const allMatches = response.data.matches || [];
            const filteredMatches = allMatches.filter(match => {
                const matchDate = match.utcDate.split('T')[0];
                return matchDate === date;
            });

            setFixtures(filteredMatches);
        } catch (err) {
            console.error(err);
            setError("Failed to fetch fixtures. Check backend or API key.");
        } finally {
            setLoadingFixtures(false);
        }
    };

    const toggleMatchSelection = (match) => {
        setSelectedMatches(prev => {
            const isSelected = prev.some(m => m.id === match.id);
            if (isSelected) {
                return prev.filter(m => m.id !== match.id);
            } else {
                return [...prev, match];
            }
        });
    };

    const handleAnalyze = async () => {
        if (selectedMatches.length === 0) return;

        setAnalyzing(true);
        setPredictions([]);

        try {
            const response = await axios.post(`${API_URL}/predict-batch`, {
                match_ids: selectedMatches.map(m => m.id)
            });
            setPredictions(response.data);
        } catch (err) {
            console.error(err);
            setError("Analysis failed. Please try again.");
        } finally {
            setAnalyzing(false);
        }
    };

    const handleAutoGenerate = async () => {
        if (selectedMatches.length === 0) return;

        setAnalyzing(true);
        setPredictions([]);

        try {
            const response = await axios.post(`${API_URL}/predict-batch`, {
                match_ids: selectedMatches.map(m => m.id)
            });

            const results = response.data;
            setPredictions(results);

            // Auto-add safe bets to the context
            results.forEach(prediction => {
                if (!prediction.error) {
                    const bet = {
                        match_id: prediction.match_id || Math.random(),
                        match: prediction.match,
                        selection: prediction.safe_bet_tip,
                        odds: 1.85 // Mock odds as placeholder
                    };
                    addToSlip(bet);
                }
            });

            // Clear queue on success
            setSelectedMatches([]);

        } catch (err) {
            console.error(err);
            setError("Auto-Generate failed. Please try again.");
        } finally {
            setAnalyzing(false);
        }
    };

    return (
        <div className="min-h-screen bg-gray-900 text-white p-6 font-sans">
            <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between border-b border-gray-800 pb-4 gap-4">
                <div>
                    <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent flex items-center gap-2">
                        <Trophy className="text-blue-400" /> OmniBet AI
                    </h1>
                    <div className="text-sm text-gray-400 mt-1">JIT RAG Powered Engine</div>
                </div>

                {/* Tab Navigation */}
                <div className="flex bg-gray-900 rounded-lg p-1 border border-gray-700">
                    <button
                        onClick={() => setActiveTab('calendar')}
                        className={`px-4 py-2 rounded-md font-medium text-sm transition-all ${activeTab === 'calendar'
                            ? 'bg-gray-800 text-purple-400 shadow-sm'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        📅 Calendar
                    </button>
                    <button
                        onClick={() => setActiveTab('history')}
                        className={`px-4 py-2 rounded-md font-medium text-sm transition-all ${activeTab === 'history'
                            ? 'bg-gray-800 text-purple-400 shadow-sm'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        📜 History
                    </button>
                </div>
            </header>

            {activeTab === 'history' && <HistoryTab onSelectHistoryItem={handleSelectHistoryItem} />}

            {activeTab === 'calendar' && (
                <main className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    {/* Left Column: Match Selection */}
                    <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
                        <div className="flex items-center justify-between mb-6">
                            <h2 className="text-xl font-semibold flex items-center gap-2">
                                <Calendar className="w-5 h-5 text-purple-400" /> Select Matches
                            </h2>
                            <input
                                type="date"
                                value={date}
                                onChange={(e) => setDate(e.target.value)}
                                className="bg-gray-700 border border-gray-600 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                            />
                        </div>

                        {loadingFixtures ? (
                            <div className="flex justify-center py-12">
                                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
                            </div>
                        ) : fixtures.length === 0 ? (
                            <div className="text-center py-12 text-gray-500">
                                {date ? "No matches found for this date." : "Please select a date to view matches."}
                            </div>
                        ) : (
                            <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2 custom-scrollbar">
                                {fixtures.map(match => (
                                    <div
                                        key={match.id}
                                        onClick={() => toggleMatchSelection(match)}
                                        className={`p-4 rounded-lg cursor-pointer transition-all border ${selectedMatches.some(m => m.id === match.id)
                                            ? 'bg-purple-900/40 border-purple-500'
                                            : 'bg-gray-700/50 border-gray-600 hover:bg-gray-700'
                                            }`}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className={`w-5 h-5 rounded border flex items-center justify-center ${selectedMatches.some(m => m.id === match.id) ? 'bg-purple-500 border-purple-500' : 'border-gray-500'
                                                }`}>
                                                {selectedMatches.some(m => m.id === match.id) && <CheckCircle className="w-3.5 h-3.5 text-white" />}
                                            </div>
                                            <div className="flex-1">
                                                <div className="flex justify-between items-center">
                                                    <span className="font-semibold text-gray-200">{match.homeTeam.name}</span>
                                                    <span className="text-xs text-gray-400">vs</span>
                                                    <span className="font-semibold text-gray-200">{match.awayTeam.name}</span>
                                                </div>
                                                <div className="text-xs text-gray-400 mt-1">
                                                    {new Date(match.utcDate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {match.competition.name}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        <div className="mt-6 pt-4 border-t border-gray-700 space-y-3">
                            <button
                                onClick={handleAnalyze}
                                disabled={selectedMatches.length === 0 || analyzing}
                                className={`w-full py-3 rounded-lg font-bold flex items-center justify-center gap-2 transition-all ${selectedMatches.length === 0 || analyzing
                                    ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                    : 'bg-gray-700 hover:bg-gray-600 text-white border border-gray-600'
                                    }`}
                            >
                                {analyzing ? (
                                    <>
                                        <Loader2 className="w-5 h-5 animate-spin" />
                                        Analyzing...
                                    </>
                                ) : (
                                    <>
                                        <Search className="w-5 h-5" />
                                        Manual Analyze ({selectedMatches.length})
                                    </>
                                )}
                            </button>

                            <button
                                onClick={handleAutoGenerate}
                                disabled={selectedMatches.length === 0 || analyzing}
                                className={`w-full py-3 rounded-lg font-bold flex items-center justify-center gap-2 transition-all ${selectedMatches.length === 0 || analyzing
                                    ? 'bg-gray-600/50 text-gray-500 cursor-not-allowed hidden'
                                    : 'bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 text-white shadow-lg shadow-green-900/20'
                                    }`}
                            >
                                {analyzing ? (
                                    <>
                                        <Loader2 className="w-5 h-5 animate-spin" />
                                        Generating Safe Bets...
                                    </>
                                ) : (
                                    <>
                                        <Zap className="w-5 h-5 text-yellow-300 fill-current" />
                                        Auto-Generate Bet Slip ({selectedMatches.length})
                                    </>
                                )}
                            </button>

                            {selectedMatches.length > 0 && (
                                <div className="mt-4 bg-gray-700/30 rounded-lg p-4 border border-gray-700">
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-sm font-semibold text-gray-300">Selected Matches ({selectedMatches.length})</span>
                                        <button
                                            onClick={() => setSelectedMatches([])}
                                            className="text-xs text-red-400 hover:text-red-300 underline"
                                        >
                                            Clear All
                                        </button>
                                    </div>
                                    <div className="space-y-2 max-h-32 overflow-y-auto custom-scrollbar">
                                        {selectedMatches
                                            .map(m => (
                                                <div key={m.id} className="flex justify-between items-center text-xs bg-gray-800 p-2 rounded">
                                                    <span className="truncate max-w-[200px]">{m.homeTeam?.name} vs {m.awayTeam?.name}</span>
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); toggleMatchSelection(m); }}
                                                        className="text-gray-500 hover:text-white"
                                                    >
                                                        ×
                                                    </button>
                                                </div>
                                            ))
                                        }
                                    </div>
                                </div>
                            )}

                            {analyzing && (
                                <p className="text-xs text-center text-gray-400 mt-2">
                                    Respecting API rate limits (24s delay per match for Deep Form Analysis). Please wait.
                                </p>
                            )}
                            {error && <p className="text-sm text-red-400 mt-2 text-center">{error}</p>}
                        </div>
                    </div>

                    {/* Right Column: Predictions */}
                    <div className="space-y-6 lg:mr-80"> {/* Margin to prevent overlap with sidebar */}
                        <h2 className="text-xl font-semibold flex items-center gap-2">
                            <Trophy className="w-5 h-5 text-yellow-500" /> AI Predictions
                        </h2>

                        {predictions.length === 0 && !analyzing && (
                            <div className="bg-gray-800/50 border border-dashed border-gray-700 rounded-xl p-12 text-center text-gray-500">
                                Select matches and click analyze to see JIT RAG predictions here.
                            </div>
                        )}

                        {predictions.map((pred, i) => (
                            <PredictionCard key={i} prediction={pred} />
                        ))}
                    </div>
                </main>
            )}
        </div>
    );
};

export default Dashboard;
