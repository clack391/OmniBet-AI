import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { Calendar, CheckCircle, Search, Trophy, AlertCircle, Loader2, Zap, LogIn, LogOut, ShieldAlert, FolderOpen, Send, Plus, Check, X, Scale, Gavel } from 'lucide-react';
import PredictionCard from './PredictionCard';
import SupremeCourtCard from './SupremeCourtCard';
import HistoryTab from './HistoryTab';
import GroupsTab from './GroupsTab';
import SettingsTab from './SettingsTab';
import AdminTerminal from './AdminTerminal';
import { useBetSlip } from '../context/BetSlipContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
    timeout: 1800000 // 30 minutes
});

// Axios Request Interceptor to inject JWT token
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const Dashboard = () => {
    const abortControllerRef = useRef(null);
    const cancelRequestedRef = useRef(false);
    const currentlyProcessingIdRef = useRef(null);

    const handleStopAnalysis = async () => {
        if (!analyzing) return;

        console.log("🛑 Stopping analysis...");
        cancelRequestedRef.current = true;

        // 1. Abort any active Axios request
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }

        // 2. Clear all polling timers
        Object.values(pollingTimersRef.current).forEach(clearInterval);
        pollingTimersRef.current = {};

        // 3. Cancel all pending background jobs via the new endpoint
        const saved = JSON.parse(localStorage.getItem('omnibetPendingJobs') || '{}');
        Object.entries(saved).forEach(([matchId, jobId]) => {
            api.post(`/jobs/${jobId}/cancel`).catch(() => {});
            removePendingJob(matchId);
        });

        // 4. Clear state
        setAnalyzing(false);
        setProgressInfo({ current: 0, total: 0, matchName: '' });
        setTerminalJobId(null);
        currentlyProcessingIdRef.current = null;
    };

    const getLogoUrl = (logoPath) => {
        if (!logoPath) return null;
        if (logoPath.startsWith('http') || logoPath.startsWith(API_URL)) return logoPath;
        const path = logoPath.startsWith('/') ? logoPath : `/${logoPath}`;
        return `${API_URL}${path}`;
    };

    const { betSlip, addToSlip } = useBetSlip();

    const findMarketOdds = (prediction, tip) => {
        if (!prediction.odds_data || !tip) return null;
        const normalizedTip = tip.toLowerCase().replace(/[\s\-_]/g, '');

        const allOutcomes = [];
        prediction.odds_data.forEach(bookie => {
            bookie.markets?.forEach(market => {
                market.outcomes?.forEach(outcome => {
                    allOutcomes.push({
                        name: outcome.name,
                        price: outcome.price,
                        point: outcome.point
                    });
                });
            });
        });

        for (const outcome of allOutcomes) {
            const name = outcome.name?.toLowerCase() || '';
            if (normalizedTip.includes(name.replace(/\s/g, ''))) return outcome.price;
            if (outcome.point) {
                if (normalizedTip.includes('over') && name.includes('over') && normalizedTip.includes(outcome.point.toString())) return outcome.price;
                if (normalizedTip.includes('under') && name.includes('under') && normalizedTip.includes(outcome.point.toString())) return outcome.price;
            }
            if (normalizedTip.includes('draw') && name.includes('draw')) return outcome.price;
            if ((normalizedTip.includes('btts') || normalizedTip.includes('bothteams')) &&
                ((normalizedTip.includes('yes') && name.includes('yes')) || (normalizedTip.includes('no') && name.includes('no')))) return outcome.price;
        }
        return null;
    };

    const handleAddAudit = (pred, customPick = null, customType = null) => {
        const tipStr = customPick?.tip || customPick || pred.audit_verdict?.ai_recommended_bet;
        if (!tipStr) return;

        const type = customType || 'Auditor Recommendation';
        // Try to find real market odds from the odds_data payload
        let extractedOdds = typeof customPick === 'object' && customPick?.odds ? parseFloat(customPick.odds) : null;

        if (!extractedOdds) {
            extractedOdds = findMarketOdds(pred, tipStr);
        }

        // Final AI fallback if no market odds found
        const aiFallbackOdds = pred.audit_verdict?.estimated_odds ? parseFloat(pred.audit_verdict.estimated_odds) :
            (type === 'Value' ? 2.50 : 1.85);

        const bet = {
            match_id: pred.match_id || Math.random(),
            match: `${pred.home_team || 'Home'} vs ${pred.away_team || 'Away'}`,
            match_date: pred.match_date,
            selection: tipStr,
            market: customPick?.market || pred.audit_verdict?.market || '',
            type: type, // 'Primary' or 'Value'
            odds: extractedOdds || aiFallbackOdds
        };
        addToSlip(bet);
    };

    const isAuditAdded = (pred, tipStr = null) => {
        const targetTip = tipStr || pred.audit_verdict?.ai_recommended_bet;
        if (!targetTip) return false;
        return betSlip.some(bet => bet.match_id === pred.match_id && bet.selection === targetTip);
    };

    const [date, setDate] = useState('');
    const [fixtures, setFixtures] = useState([]);
    const [selectedMatches, setSelectedMatches] = useState([]); // Now stores full match objects: { id, homeTeam, awayTeam }
    const [loadingFixtures, setLoadingFixtures] = useState(false);
    const [analyzing, setAnalyzing] = useState(false);
    const [progressInfo, setProgressInfo] = useState({ current: 0, total: 0, matchName: '' });
    const [predictions, setPredictions] = useState([]);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('calendar');
    const [historyTabMounted, setHistoryTabMounted] = useState(false);
    const [bookingCode, setBookingCode] = useState('');
    const [activeBookingCode, setActiveBookingCode] = useState(null);
    const [isParsingCode, setIsParsingCode] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    // Admin Auth State
    const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('token'));
    const [showLoginModal, setShowLoginModal] = useState(false);
    const [loginForm, setLoginForm] = useState({ username: '', password: '' });
    const [loginLoading, setLoginLoading] = useState(false);
    const [loginError, setLoginError] = useState('');

    // Async job tracking state (Walk-Away feature)
    const [pendingJobs, setPendingJobs] = useState({});   // { match_id: job_id }
    const [terminalJobId, setTerminalJobId] = useState(null);
    const pollingTimersRef = useRef({});                   // { job_id: intervalId }

    // Axios Response Interceptor to handle expired/invalid tokens globally
    useEffect(() => {
        const interceptor = api.interceptors.response.use(
            (response) => response,
            (error) => {
                if (error.response && (error.response.status === 401 || error.response.status === 403)) {
                    localStorage.removeItem('token');
                    setIsLoggedIn(false);
                    setShowLoginModal(true); // Prompt them to log back in
                }
                return Promise.reject(error);
            }
        );
        return () => api.interceptors.response.eject(interceptor);
    }, []);

    // --- Walk-Away: reconnect to any pending jobs on mount ---
    useEffect(() => {
        if (!isLoggedIn) return;
        let saved;
        try {
            saved = JSON.parse(localStorage.getItem('omnibetPendingJobs') || '{}');
        } catch {
            saved = {};
        }
        if (Object.keys(saved).length === 0) return;

        const resumeJob = async (matchId, jobId) => {
            try {
                const res = await api.get(`/jobs/${jobId}`);
                const job = res.data;
                if (job.status === 'COMPLETED' && job.result) {
                    setPredictions(prev => {
                        const alreadyPresent = prev.some(p => p.match_id === job.result.match_id);
                        return alreadyPresent ? prev : [...prev, job.result];
                    });
                    removePendingJob(matchId);
                } else if (job.status === 'FAILED' || job.status === 'CANCELLED') {
                    removePendingJob(matchId);
                } else {
                    // Still running — start polling
                    setTerminalJobId(jobId);
                    startPolling(matchId, jobId);
                }
            } catch {
                removePendingJob(matchId);
            }
        };

        Object.entries(saved).forEach(([matchId, jobId]) => resumeJob(matchId, jobId));
    }, [isLoggedIn]); // eslint-disable-line react-hooks/exhaustive-deps

    const savePendingJob = (matchId, jobId) => {
        const current = JSON.parse(localStorage.getItem('omnibetPendingJobs') || '{}');
        current[matchId] = jobId;
        localStorage.setItem('omnibetPendingJobs', JSON.stringify(current));
        setPendingJobs(prev => ({ ...prev, [matchId]: jobId }));
    };

    const removePendingJob = (matchId) => {
        const current = JSON.parse(localStorage.getItem('omnibetPendingJobs') || '{}');
        delete current[matchId];
        localStorage.setItem('omnibetPendingJobs', JSON.stringify(current));
        setPendingJobs(prev => { const n = { ...prev }; delete n[matchId]; return n; });
    };

    const startPolling = (matchId, jobId) => {
        if (pollingTimersRef.current[jobId]) return; // already polling
        const intervalId = setInterval(async () => {
            try {
                const res = await api.get(`/jobs/${jobId}`);
                const job = res.data;
                if (job.status === 'COMPLETED' && job.result) {
                    clearInterval(pollingTimersRef.current[jobId]);
                    delete pollingTimersRef.current[jobId];
                    setPredictions(prev => {
                        const alreadyPresent = prev.some(p => p.match_id === job.result.match_id);
                        return alreadyPresent ? prev : [...prev, job.result];
                    });
                    removePendingJob(matchId);
                    setAnalyzing(prev => {
                        // Only turn off spinner when all jobs are done
                        const remaining = Object.keys(pollingTimersRef.current).length;
                        return remaining > 0 ? prev : false;
                    });
                } else if (job.status === 'FAILED' || job.status === 'CANCELLED') {
                    clearInterval(pollingTimersRef.current[jobId]);
                    delete pollingTimersRef.current[jobId];
                    removePendingJob(matchId);
                    setError(`Job for match ${matchId} ${job.status.toLowerCase()}: ${job.error_msg || ''}`);
                }
            } catch {
                // Network blip — keep polling
            }
        }, 3000);
        pollingTimersRef.current[jobId] = intervalId;
    };

    const handleLogin = async (e) => {
        e.preventDefault();
        setLoginLoading(true);
        setLoginError('');
        try {
            const formData = new URLSearchParams();
            formData.append('username', loginForm.username);
            formData.append('password', loginForm.password);

            const response = await axios.post(`${API_URL}/login`, formData, {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
            });

            if (response.data.role !== 'admin') {
                setLoginError("This account does not have admin privileges.");
                return;
            }

            localStorage.setItem('token', response.data.access_token);
            setIsLoggedIn(true);
            setShowLoginModal(false);
        } catch (err) {
            setLoginError(err.response?.data?.detail || "Login failed.");
        } finally {
            setLoginLoading(false);
        }
    };

    const handleLogout = () => {
        localStorage.removeItem('token');
        setIsLoggedIn(false);
    };

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

            const response = await api.get(`/fixtures`, {
                params: {
                    start_date: date,
                    end_date: nextDate
                }
            });

            // Filter matches to only include those on the selected date IN WAT (Africa/Lagos, UTC+1).
            // IMPORTANT: We must NOT use the raw UTC date string — a match at 23:30 UTC on March 20
            // is actually 00:30 WAT on March 21. We must convert to WAT first.
            const allMatches = response.data.matches || [];
            const filteredMatches = allMatches.filter(match => {
                if (!match.utcDate) return false;
                // Convert the UTC ISO timestamp to WAT date string (YYYY-MM-DD)
                const matchDate = new Date(match.utcDate);
                const watDateStr = matchDate.toLocaleDateString('en-CA', {
                    timeZone: 'Africa/Lagos' // WAT = UTC+1
                }); // returns 'YYYY-MM-DD' format
                return watDateStr === date;
            });

            setFixtures(filteredMatches);

        } catch (err) {
            console.error(err);
            setError("Failed to fetch fixtures. Check backend or API key.");
        } finally {
            setLoadingFixtures(false);
        }
    };

    // Team abbreviation mappings for smart search
    const getTeamAbbreviations = (teamName) => {
        const name = teamName.toLowerCase();
        const abbreviations = [name]; // Always include the full name

        // Common abbreviation patterns
        const abbrevMap = {
            'manchester city': ['man city', 'man c', 'mcfc', 'city'],
            'manchester united': ['man united', 'man u', 'man utd', 'mufc', 'united'],
            'tottenham hotspur': ['spurs', 'tottenham', 'thfc'],
            'arsenal': ['arsenal fc', 'afc', 'gunners'],
            'chelsea': ['chelsea fc', 'cfc', 'blues'],
            'liverpool': ['liverpool fc', 'lfc', 'reds'],
            'real madrid': ['real', 'madrid', 'rmcf', 'rm'],
            'fc barcelona': ['barcelona', 'barca', 'barça', 'fcb', 'barca'],
            'barcelona': ['barca', 'barça', 'fcb', 'fc barcelona'],
            'atletico madrid': ['atletico', 'atleti', 'atm'],
            'atlético madrid': ['atletico', 'atleti', 'atm'],
            'paris saint-germain': ['psg', 'paris', 'paris sg'],
            'bayern munich': ['bayern', 'fcb', 'fcbayern'],
            'borussia dortmund': ['dortmund', 'bvb', 'bvb 09'],
            'inter milan': ['inter', 'internazionale', 'fc inter'],
            'ac milan': ['milan', 'acm', 'ac'],
            'juventus': ['juve', 'juventus fc', 'jfc'],
            'newcastle united': ['newcastle', 'nufc', 'toon', 'magpies'],
            'west ham united': ['west ham', 'whu', 'hammers'],
            'aston villa': ['villa', 'avfc'],
            'brighton': ['brighton & hove albion', 'bhafc', 'seagulls'],
            'nottingham forest': ['notts forest', 'forest', 'nffc'],
            'leicester city': ['leicester', 'lcfc', 'foxes'],
            'crystal palace': ['palace', 'cpfc', 'eagles'],
            'olympique lyonnais': ['lyon', 'ol', 'olympique lyon'],
            'olympique de marseille': ['marseille', 'om', 'olympique marseille'],
            'as monaco': ['monaco', 'asm'],
            'ajax': ['ajax amsterdam', 'afc ajax'],
            'psv eindhoven': ['psv', 'psv eindhoven'],
            'fc porto': ['porto', 'fcp'],
            'sporting cp': ['sporting', 'sporting lisbon', 'scp'],
            'benfica': ['sl benfica', 'slb'],
        };

        // Check if team name matches any key in abbreviations map
        for (const [fullName, abbrevs] of Object.entries(abbrevMap)) {
            if (name.includes(fullName) || fullName.includes(name)) {
                abbreviations.push(...abbrevs);
                break;
            }
        }

        // Add generic abbreviations for any team name
        // e.g., "FC Barcelona" -> "barcelona", "fc"
        const words = name.split(/\s+/);
        if (words.length > 1) {
            // Add each individual word
            abbreviations.push(...words.filter(w => w.length > 2));

            // Add first letters of each word (e.g., "Real Madrid" -> "rm")
            const initials = words.map(w => w[0]).join('');
            if (initials.length >= 2) {
                abbreviations.push(initials);
            }
        }

        return [...new Set(abbreviations)]; // Remove duplicates
    };

    // Filter matches based on search query using useMemo for performance
    const filteredFixtures = useMemo(() => {
        if (!searchQuery.trim()) return fixtures;

        const query = searchQuery.toLowerCase().trim();

        // Filter and score matches
        const matchesWithScore = fixtures.map(match => {
            const homeTeamName = match.homeTeam?.name?.toLowerCase() || '';
            const awayTeamName = match.awayTeam?.name?.toLowerCase() || '';

            // Get all possible abbreviations for both teams
            const homeAbbrevs = getTeamAbbreviations(homeTeamName);
            const awayAbbrevs = getTeamAbbreviations(awayTeamName);

            let score = 0;
            let matches = false;

            // Check home team
            if (homeTeamName === query) {
                score = 1000; // Exact match gets highest priority
                matches = true;
            } else if (homeTeamName.startsWith(query)) {
                score = 100; // Starts with query
                matches = true;
            } else if (homeAbbrevs.some(abbrev => abbrev === query)) {
                score = 90; // Exact abbreviation match
                matches = true;
            } else if (homeAbbrevs.some(abbrev => abbrev.includes(query) || query.includes(abbrev))) {
                score = 50; // Partial match
                matches = true;
            }

            // Check away team (same scoring)
            if (awayTeamName === query) {
                score = Math.max(score, 1000);
                matches = true;
            } else if (awayTeamName.startsWith(query)) {
                score = Math.max(score, 100);
                matches = true;
            } else if (awayAbbrevs.some(abbrev => abbrev === query)) {
                score = Math.max(score, 90);
                matches = true;
            } else if (awayAbbrevs.some(abbrev => abbrev.includes(query) || query.includes(abbrev))) {
                score = Math.max(score, 50);
                matches = true;
            }

            return { match, score, matches };
        })
        .filter(item => item.matches) // Only keep matches
        .sort((a, b) => b.score - a.score); // Sort by score (highest first)

        return matchesWithScore.map(item => item.match);
    }, [fixtures, searchQuery]);

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

    // --- Resilient API wrapper: auto-retries when mobile browser kills connection ---
    const waitForPageVisible = () => {
        return new Promise((resolve) => {
            if (document.visibilityState === 'visible') {
                resolve();
                return;
            }
            const handler = () => {
                if (document.visibilityState === 'visible') {
                    document.removeEventListener('visibilitychange', handler);
                    // Small delay to let network reconnect after screen wake
                    setTimeout(resolve, 1500);
                }
            };
            document.addEventListener('visibilitychange', handler);
        });
    };

    const resilientApiCall = async (callFn, matchLabel, maxRetries = 3) => {
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                return await callFn();
            } catch (err) {
                const isNetworkError = !err.response; // No server response = connection dropped
                if (isNetworkError && attempt < maxRetries) {
                    console.warn(`⚠️ Connection lost for "${matchLabel}". Waiting for screen...`);
                    setProgressInfo(prev => ({ ...prev, matchName: `📡 Reconnecting... (${matchLabel})` }));
                    await waitForPageVisible();
                    console.log(`🔄 Screen back. Retrying "${matchLabel}" (attempt ${attempt + 1})...`);
                    continue;
                }
                throw err; // Genuine server error or max retries exhausted
            }
        }
    };

    const handleAnalyze = async () => {
        if (selectedMatches.length === 0) return;

        setAnalyzing(true);
        setPredictions([]);
        setError(null);
        cancelRequestedRef.current = false;
        const total = selectedMatches.length;

        try {
            // Submit ALL jobs immediately (no waiting) then poll each for results
            for (let i = 0; i < total; i++) {
                if (cancelRequestedRef.current) break;

                const match = selectedMatches[i];
                const matchLabel = `${match.homeTeam?.name || 'Team'} vs ${match.awayTeam?.name || 'Team'}`;
                setProgressInfo({ current: i + 1, total, matchName: `Queuing: ${matchLabel}` });

                try {
                    const res = await api.post('/predict-async', { match_ids: [match.id] });
                    const jobInfo = res.data[0]; // { job_id, match_id, status }
                    savePendingJob(match.id, jobInfo.job_id);
                    // Show terminal for the first (or latest) job
                    setTerminalJobId(jobInfo.job_id);
                    startPolling(match.id, jobInfo.job_id);
                } catch (err) {
                    console.error(`Failed to queue ${matchLabel}:`, err);
                }
            }

            setProgressInfo({ current: total, total, matchName: '⏳ Analyzing in background…' });
        } catch (err) {
            if (axios.isCancel(err) || err.name === 'AbortError' || cancelRequestedRef.current) {
                console.log("Analysis aborted by user.");
                return;
            }
            console.error(err);
            setError("Failed to queue analysis. Please try again.");
            setAnalyzing(false);
            setProgressInfo({ current: 0, total: 0, matchName: '' });
        }
        // Note: setAnalyzing(false) is handled inside startPolling when the last job completes
    };

    const handleAutoGenerate = async () => {
        if (selectedMatches.length === 0) return;

        setAnalyzing(true);
        setPredictions([]);
        setError(null);
        cancelRequestedRef.current = false;
        const total = selectedMatches.length;

        // Auto-add picks to slip as each job completes — wrap startPolling with auto-add logic
        const startAutoGeneratePolling = (matchId, jobId) => {
            if (pollingTimersRef.current[jobId]) return;
            const intervalId = setInterval(async () => {
                try {
                    const res = await api.get(`/jobs/${jobId}`);
                    const job = res.data;
                    if (job.status === 'COMPLETED' && job.result) {
                        clearInterval(pollingTimersRef.current[jobId]);
                        delete pollingTimersRef.current[jobId];
                        const result = job.result;
                        setPredictions(prev => {
                            const alreadyPresent = prev.some(p => p.match_id === result.match_id);
                            return alreadyPresent ? prev : [...prev, result];
                        });
                        removePendingJob(matchId);
                        // Auto-add to bet slip
                        if (result && !result.error) {
                            const primaryPick = result.primary_pick;
                            const tipToAdd = primaryPick?.tip || result.safe_bet_tip || "Unknown Tip";
                            const oddsToAdd = primaryPick?.odds ? parseFloat(primaryPick.odds) : 1.85;
                            addToSlip({
                                match_id: result.match_id || Math.random(),
                                match: result.match,
                                match_date: result.match_date,
                                selection: tipToAdd,
                                market: primaryPick?.market || result.market || '',
                                type: 'Primary',
                                odds: oddsToAdd,
                            });
                        }
                        const remaining = Object.keys(pollingTimersRef.current).length;
                        if (remaining === 0) {
                            setAnalyzing(false);
                            setProgressInfo({ current: 0, total: 0, matchName: '' });
                            setSelectedMatches([]);
                        }
                    } else if (job.status === 'FAILED' || job.status === 'CANCELLED') {
                        clearInterval(pollingTimersRef.current[jobId]);
                        delete pollingTimersRef.current[jobId];
                        removePendingJob(matchId);
                        const remaining = Object.keys(pollingTimersRef.current).length;
                        if (remaining === 0) {
                            setAnalyzing(false);
                            setProgressInfo({ current: 0, total: 0, matchName: '' });
                        }
                    }
                } catch {
                    // Network blip — keep polling
                }
            }, 3000);
            pollingTimersRef.current[jobId] = intervalId;
        };

        try {
            for (let i = 0; i < total; i++) {
                if (cancelRequestedRef.current) break;
                const match = selectedMatches[i];
                const matchLabel = `${match.homeTeam?.name || 'Team'} vs ${match.awayTeam?.name || 'Team'}`;
                setProgressInfo({ current: i + 1, total, matchName: `Queuing: ${matchLabel}` });
                try {
                    const res = await api.post('/predict-async', { match_ids: [match.id] });
                    const jobInfo = res.data[0];
                    savePendingJob(match.id, jobInfo.job_id);
                    setTerminalJobId(jobInfo.job_id);
                    startAutoGeneratePolling(match.id, jobInfo.job_id);
                } catch (err) {
                    console.error(`Failed to queue ${matchLabel}:`, err);
                }
            }
            setProgressInfo({ current: total, total, matchName: '⏳ Analyzing in background…' });
        } catch (err) {
            if (axios.isCancel(err) || err.name === 'AbortError' || cancelRequestedRef.current) {
                console.log("Auto-Generate aborted by user.");
                return;
            }
            console.error(err);
            setError("Auto-Generate failed. Please try again.");
            setAnalyzing(false);
            setProgressInfo({ current: 0, total: 0, matchName: '' });
        }
    };

    const handleAudit = async () => {
        if (selectedMatches.length === 0) return;

        setAnalyzing(true);
        setPredictions([]);
        setError(null);
        cancelRequestedRef.current = false;
        const total = selectedMatches.length;

        try {
            for (let i = 0; i < total; i++) {
                if (cancelRequestedRef.current) break;

                const match = selectedMatches[i];
                const matchLabel = `${match.homeTeam?.name || 'Team'} vs ${match.awayTeam?.name || 'Team'}`;
                setProgressInfo({ current: i + 1, total, matchName: `Queuing audit: ${matchLabel}` });

                try {
                    const res = await api.post('/audit-async', {
                        booking_code: activeBookingCode || null,
                        items: [{
                            match_id: match.id || match.match_id,
                            user_selected_bet: match._user_selected_bet || match.selection || "Unknown Bet"
                        }]
                    });
                    const jobInfo = res.data[0]; // { job_id, match_id, status }
                    savePendingJob(match.id || match.match_id, jobInfo.job_id);
                    setTerminalJobId(jobInfo.job_id);
                    startPolling(match.id || match.match_id, jobInfo.job_id);
                } catch (err) {
                    console.error(`Failed to queue audit for ${matchLabel}:`, err);
                }
            }
            setProgressInfo({ current: total, total, matchName: '⏳ Auditing in background…' });
        } catch (err) {
            if (axios.isCancel(err) || err.name === 'AbortError' || cancelRequestedRef.current) {
                console.log("Audit aborted by user.");
                return;
            }
            console.error(err);
            setError("Betslip Auditor failed. Please try again.");
            setAnalyzing(false);
            setProgressInfo({ current: 0, total: 0, matchName: '' });
        }
    };

    const handleParseBookingCode = async () => {
        if (!bookingCode.trim()) return;
        setIsParsingCode(true);
        setError('');

        try {
            const response = await api.post('/api/sportybet/parse', {
                booking_code: bookingCode.trim()
            });

            const rawMatches = response.data.matches;
            if (!rawMatches || rawMatches.length === 0) {
                setError("No valid matches could be found in that booking code.");
                return;
            }

            const matchedFixtures = response.data.enriched_matches || [];
            const unmatchedNames = response.data.unmatched_names || [];

            // Automatically select the successfully matched fixtures cross-date
            setSelectedMatches(prev => {
                const newSelection = [...prev];
                matchedFixtures.forEach(mf => {
                    // Make sure we use the internal ID for deduplication
                    if (!newSelection.some(selected => selected.id === mf.id)) {
                        newSelection.push(mf);
                    }
                });
                return newSelection;
            });

            if (unmatchedNames.length > 0) {
                setError(`Successfully imported ${matchedFixtures.length} games. Could not locate: ${unmatchedNames.join(', ')} anywhere in the 7-day database.`);
            } else {
                setError(`Successfully imported all ${matchedFixtures.length} games to your slip!`);
                // Auto clear on complete success
                setTimeout(() => setError(''), 4000);
            }

            setActiveBookingCode(bookingCode.trim());
            setBookingCode(''); // Clear input

        } catch (err) {
            console.error("Booking parse error:", err);
            setError(err.response?.data?.detail || "Failed to parse booking code. Please try again.");
        } finally {
            setIsParsingCode(false);
        }
    };

    return (
        <div className="min-h-screen bg-gray-950 text-white p-4 md:p-8 font-sans">
            <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between border-b border-gray-800/50 pb-6 gap-6">
                <div>
                    <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent flex items-center gap-2">
                        <Trophy className="text-blue-400" /> OmniBet AI
                    </h1>
                    <div className="text-sm text-gray-400 mt-1">JIT RAG Powered Engine</div>
                </div>

                {/* Community and Admin Controls */}
                <div className="flex flex-wrap items-center gap-2 md:gap-3">
                    <a
                        href="https://t.me/+8omIp4SuGL84ZGU0"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 px-3 py-1.5 text-xs md:text-sm font-medium text-sky-400 hover:text-white transition-colors bg-sky-900/20 border border-sky-500/30 hover:bg-sky-500/20 rounded-md"
                    >
                        <Send className="w-3.5 h-3.5 md:w-4 md:h-4" /> <span className="hidden sm:inline">Join</span> Telegram
                    </a>

                    <div className="flex bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                        {isLoggedIn ? (
                            <button
                                onClick={handleLogout}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs md:text-sm text-gray-400 hover:text-white transition-colors border border-gray-700/50 rounded-md"
                            >
                                <LogOut className="w-3.5 h-3.5 md:w-4 md:h-4" /> <span className="hidden sm:inline">Admin </span>Logout
                            </button>
                        ) : (
                            <button
                                onClick={() => setShowLoginModal(true)}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs md:text-sm font-medium text-emerald-400 hover:text-white transition-colors bg-emerald-900/20 border border-emerald-500/30 hover:bg-emerald-500/20 rounded-md"
                            >
                                <ShieldAlert className="w-3.5 h-3.5 md:w-4 md:h-4" /> <span className="hidden sm:inline">Admin </span>Access
                            </button>
                        )}
                    </div>
                </div>

                {/* Tab Navigation */}
                <div className="flex bg-gray-900 rounded-lg p-1 border border-gray-700 overflow-x-auto custom-scrollbar whitespace-nowrap">
                    <button
                        onClick={() => setActiveTab('calendar')}
                        className={`px-4 py-2 rounded-md font-medium text-sm transition-all flex items-center gap-1.5 ${activeTab === 'calendar'
                            ? 'bg-gray-800 text-purple-400 shadow-sm border border-gray-700'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        <Calendar className="w-4 h-4" /> Calendar
                    </button>
                    <button
                        onClick={() => setActiveTab('groups')}
                        className={`px-4 py-2 rounded-md font-medium text-sm transition-all flex items-center gap-1.5 ${activeTab === 'groups'
                            ? 'bg-gray-800 text-blue-400 shadow-sm border border-gray-700'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        <FolderOpen className="w-4 h-4" /> Groups
                    </button>
                    <button
                        onClick={() => { setActiveTab('history'); setHistoryTabMounted(true); }}
                        className={`px-4 py-2 rounded-md font-medium text-sm transition-all flex items-center gap-1.5 ${activeTab === 'history'
                            ? 'bg-gray-800 text-indigo-400 shadow-sm border border-gray-700'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        📜 History
                    </button>
                    {isLoggedIn && (
                        <button
                            onClick={() => setActiveTab('settings')}
                            className={`px-4 py-2 rounded-md font-medium text-sm transition-all flex items-center gap-1.5 ${activeTab === 'settings'
                                ? 'bg-gray-800 text-teal-400 shadow-sm border border-gray-700'
                                : 'text-gray-400 hover:text-white'
                                }`}
                        >
                            ⚙️ Settings
                        </button>
                    )}
                </div>
            </header>

            {historyTabMounted && (
                <div style={{ display: activeTab === 'history' ? 'block' : 'none' }}>
                    <HistoryTab onSelectHistoryItem={handleSelectHistoryItem} />
                </div>
            )}
            {activeTab === 'groups' && <GroupsTab onSelectHistoryItem={handleSelectHistoryItem} />}
            {activeTab === 'settings' && isLoggedIn && <SettingsTab />}

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
                                onChange={(e) => { setDate(e.target.value); setSearchQuery(''); }}
                                className="bg-gray-700 border border-gray-600 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                            />
                        </div>

                        {/* Search Input */}
                        {date && fixtures.length > 0 && (
                            <div className="mb-4 relative">
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    <input
                                        type="text"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        placeholder="Search matches by team name..."
                                        className="w-full bg-gray-700 border border-gray-600 rounded-lg pl-10 pr-10 py-2.5 text-sm text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all"
                                    />
                                    {searchQuery && (
                                        <button
                                            onClick={() => setSearchQuery('')}
                                            className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
                                        >
                                            <X className="w-4 h-4" />
                                        </button>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Booking Code Importer */}
                        <div className="mb-6 bg-gray-700/30 rounded-lg p-3 md:p-4 border border-gray-700 flex flex-col md:flex-row gap-3 items-center">
                            <div className="flex-1 w-full text-center md:text-left">
                                <label className="block text-[10px] md:text-xs text-gray-400 mb-1">SportyBet Booking Code</label>
                                <input
                                    type="text"
                                    value={bookingCode}
                                    onChange={(e) => setBookingCode(e.target.value.toUpperCase())}
                                    placeholder="e.g. BC4DF2A..."
                                    className="w-full bg-slate-900/80 border border-slate-700/50 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 text-sm font-mono tracking-wider"
                                />
                            </div>
                            <button
                                onClick={handleParseBookingCode}
                                disabled={!bookingCode.trim() || isParsingCode}
                                className={`w-full md:w-auto mt-2 md:mt-5 px-6 py-2.5 rounded-lg font-bold text-sm flex items-center justify-center gap-2 transition-all shadow-lg ${!bookingCode.trim() || isParsingCode
                                    ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-purple-900/20'}`}
                            >
                                {isParsingCode ? (
                                    <>
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                        <span>Scraping...</span>
                                    </>
                                ) : (
                                    <>
                                        <Search className="w-4 h-4" />
                                        <span>Import Slip</span>
                                    </>
                                )}
                            </button>
                        </div>

                        {loadingFixtures ? (
                            <div className="flex justify-center py-12">
                                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
                            </div>
                        ) : fixtures.length === 0 ? (
                            <div className="text-center py-12 text-gray-500">
                                {date ? "No matches found for this date." : "Please select a date to view matches."}
                            </div>
                        ) : filteredFixtures.length === 0 ? (
                            <div className="text-center py-12 text-gray-400">
                                <Search className="w-8 h-8 mx-auto mb-3 text-gray-600" />
                                <p className="text-sm">No matches found for "{searchQuery}"</p>
                                <button
                                    onClick={() => setSearchQuery('')}
                                    className="mt-3 text-xs text-purple-400 hover:text-purple-300 underline"
                                >
                                    Clear search
                                </button>
                            </div>
                        ) : (
                            <>
                                {searchQuery && (
                                    <div className="mb-3 text-xs text-gray-400 flex items-center justify-between bg-gray-700/30 rounded-lg px-3 py-2 border border-gray-700/50">
                                        <span>Found {filteredFixtures.length} match{filteredFixtures.length !== 1 ? 'es' : ''}</span>
                                    </div>
                                )}
                                <div key={`matches-${searchQuery}-${filteredFixtures.length}`} className="space-y-3 max-h-[600px] overflow-y-auto pr-2 custom-scrollbar">
                                    {filteredFixtures.map(match => (
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
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex justify-between items-center gap-2">
                                                        <span className="font-semibold text-gray-200 truncate">{match.homeTeam.name}</span>
                                                        <span className="text-xs text-gray-400 shrink-0">vs</span>
                                                        <span className="font-semibold text-gray-200 truncate text-right">{match.awayTeam.name}</span>
                                                    </div>
                                                    <div className="text-xs text-gray-400 mt-1 truncate">
                                                        {new Date(match.utcDate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Lagos' })} • {match.competition.name}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}

                        <div className="mt-6 pt-4 border-t border-gray-700 space-y-3">
                            {analyzing ? (
                                <button
                                    onClick={handleStopAnalysis}
                                    className="w-full py-4 rounded-lg font-bold flex items-center justify-center gap-2 transition-all bg-red-600 hover:bg-red-500 text-white animate-pulse"
                                >
                                    <X className="w-6 h-6" />
                                    STOP ANALYSIS SHARPLY
                                </button>
                            ) : (
                                <>
                                    <button
                                        onClick={handleAnalyze}
                                        disabled={selectedMatches.length === 0 || analyzing}
                                        className={`w-full py-3 rounded-lg font-bold flex items-center justify-center gap-2 transition-all ${selectedMatches.length === 0 || analyzing
                                            ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                            : 'bg-gray-700 hover:bg-gray-600 text-white border border-gray-600'
                                            }`}
                                    >
                                        <Search className="w-5 h-5" />
                                        Manual Analyze ({selectedMatches.length})
                                    </button>

                                    <button
                                        onClick={handleAutoGenerate}
                                        disabled={selectedMatches.length === 0 || analyzing}
                                        className={`w-full py-3 rounded-lg font-bold flex items-center justify-center gap-2 transition-all ${selectedMatches.length === 0 || analyzing
                                            ? 'bg-gray-600/50 text-gray-500 cursor-not-allowed hidden'
                                            : 'bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 text-white shadow-lg shadow-green-900/20'
                                            }`}
                                    >
                                        <Zap className="w-5 h-5 text-yellow-300 fill-current" />
                                        Auto-Generate Bet Slip ({selectedMatches.length})
                                    </button>

                                    <button
                                        onClick={handleAudit}
                                        disabled={selectedMatches.length === 0 || analyzing}
                                        className={`w-full py-3 rounded-lg font-bold flex items-center justify-center gap-2 transition-all ${selectedMatches.length === 0 || analyzing
                                            ? 'bg-gray-600/50 text-gray-500 cursor-not-allowed hidden'
                                            : 'bg-gradient-to-r from-orange-500 to-red-600 hover:from-orange-400 hover:to-red-500 text-white shadow-lg shadow-red-900/20'
                                            }`}
                                    >
                                        <Scale className="w-5 h-5" />
                                        Audit Selected Matches ({selectedMatches.length})
                                    </button>
                                </>
                            )}
                        </div>

                        {selectedMatches.length > 0 && (
                            <div className="mt-4 bg-gray-700/30 rounded-lg p-4 border border-gray-700">
                                <div className="flex justify-between items-center mb-2">
                                    <span className="text-sm font-semibold text-gray-300">Selected Matches ({selectedMatches.length})</span>
                                    <button
                                        onClick={() => { setSelectedMatches([]); setActiveBookingCode(null); }}
                                        className="text-xs text-red-400 hover:text-red-300 underline"
                                    >
                                        Clear All
                                    </button>
                                </div>
                                <div className="space-y-2 max-h-32 overflow-y-auto custom-scrollbar">
                                    {selectedMatches
                                        .map(m => (
                                            <div key={m.id} className="flex justify-between items-center text-xs bg-gray-800 p-2 rounded border border-gray-700/50">
                                                <div className="flex flex-col gap-0.5 min-w-0">
                                                    <span className="truncate font-medium text-gray-200">{m.homeTeam?.name} vs {m.awayTeam?.name}</span>
                                                    {m._user_selected_bet && (
                                                        <span className="text-[10px] text-purple-400 font-bold truncate">Pick: {m._user_selected_bet}</span>
                                                    )}
                                                </div>
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); toggleMatchSelection(m); }}
                                                    className="text-gray-500 hover:text-red-400 p-1 transition-colors"
                                                >
                                                    <X className="w-3.5 h-3.5" />
                                                </button>
                                            </div>
                                        ))
                                    }
                                </div>
                            </div>
                        )}

                        {analyzing && (
                            <div className="mt-3 space-y-2">
                                <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                    <div
                                        className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-500 ease-out"
                                        style={{ width: `${progressInfo.total > 0 ? (progressInfo.current / progressInfo.total) * 100 : 0}%` }}
                                    />
                                </div>
                                <p className="text-xs text-center text-gray-400">
                                    ⚡ Analyzing: <span className="text-blue-400 font-medium">{progressInfo.matchName}</span>
                                </p>
                                <p className="text-[10px] text-center text-gray-500">
                                    Match {progressInfo.current} of {progressInfo.total} • Respecting API rate limits
                                </p>
                            </div>
                        )}
                        {error && <p className="text-sm text-red-400 mt-2 text-center">{error}</p>}
                    </div>

                    {/* Right Column: Predictions */}
                    <div className="space-y-6 lg:mr-80"> {/* Margin to prevent overlap with sidebar */}
                        <h2 className="text-xl font-semibold flex items-center gap-2">
                            <Trophy className="w-5 h-5 text-yellow-500" /> AI Predictions
                        </h2>

                        {/* Admin Live Terminal — only visible when logged in and a job is active */}
                        {isLoggedIn && terminalJobId && (
                            <AdminTerminal
                                jobId={terminalJobId}
                                token={localStorage.getItem('token')}
                                apiUrl={API_URL}
                            />
                        )}

                        {predictions.length === 0 && !analyzing && (
                            <div className="bg-gray-800/50 border border-dashed border-gray-700 rounded-xl p-12 text-center text-gray-500">
                                Select matches and click analyze to see JIT RAG predictions here.
                            </div>
                        )}

                        {predictions.map((pred, i) => {
                            try { void pred.match; } catch { return null; } // Guard against null pred
                            return pred.audit_verdict ? (
                                <div key={i} className="mb-10 space-y-4 border border-blue-900/50 rounded-2xl p-4 bg-blue-900/10">
                                    <div className="flex items-center justify-between mb-2 px-2">
                                        <div className="flex items-center gap-2 text-blue-400">
                                            <ShieldAlert className="w-5 h-5" />
                                            <span className="font-bold tracking-widest uppercase text-sm">Triple-Agent Strategic Report</span>
                                        </div>
                                    </div>

                                    {/* Agent 3: Supreme Court Ruling Component */}
                                    <SupremeCourtCard
                                        supreme_court={pred.supreme_court}
                                        handleAdd={(pick, type) => handleAddAudit(pred, pick, type)}
                                        isPickAdded={(tip) => isAuditAdded(pred, tip)}
                                    />

                                    <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden shadow-xl mb-4">
                                        <div className={`p-4 border-b ${pred.audit_verdict.status === 'APPROVED' ? 'bg-green-900/30 border-green-800' :
                                            pred.audit_verdict.status === 'DOWNGRADED' ? 'bg-yellow-900/30 border-yellow-800' :
                                                'bg-red-900/30 border-red-800'
                                            }`}>
                                            <div className="flex justify-between items-center bg-gray-900/80 px-4 py-3 rounded-xl mb-4 border border-gray-700/50 shadow-inner">
                                                <div className="flex flex-col items-center gap-2 flex-1">
                                                    <div className="w-12 h-12 rounded-full bg-white border-2 border-slate-700 shadow-lg flex items-center justify-center overflow-hidden p-1.5">
                                                        {pred.home_logo ? (
                                                            <img src={getLogoUrl(pred.home_logo)} alt="H" className="w-full h-full object-contain" />
                                                        ) : (
                                                            <span className="text-gray-400 font-bold text-xs">{pred.home_team?.substring(0, 2).toUpperCase()}</span>
                                                        )}
                                                    </div>
                                                    <span className="font-bold text-gray-200 text-xs text-center leading-tight">{pred.home_team || "Home"}</span>
                                                </div>

                                                <div className="px-4">
                                                    <span className="text-gray-600 text-sm font-black italic">VS</span>
                                                </div>

                                                <div className="flex flex-col items-center gap-2 flex-1">
                                                    <div className="w-12 h-12 rounded-full bg-white border-2 border-slate-700 shadow-lg flex items-center justify-center overflow-hidden p-1.5">
                                                        {pred.away_logo ? (
                                                            <img src={getLogoUrl(pred.away_logo)} alt="A" className="w-full h-full object-contain" />
                                                        ) : (
                                                            <span className="text-gray-400 font-bold text-xs">{pred.away_team?.substring(0, 2).toUpperCase()}</span>
                                                        )}
                                                    </div>
                                                    <span className="font-bold text-gray-200 text-xs text-center leading-tight">{pred.away_team || "Away"}</span>
                                                </div>
                                            </div>

                                            <div className="flex justify-between items-center mb-2">
                                                <div className="text-sm text-gray-400">Your Bet: <span className="text-white font-mono bg-gray-900 px-2 py-1 rounded ml-1">{pred.audit_verdict.original_bet}</span></div>
                                                <div className={`text-sm font-black px-3 py-1 rounded-full ${pred.audit_verdict.status === 'APPROVED' ? 'bg-green-500/20 text-green-400 border border-green-500/50' :
                                                    pred.audit_verdict.status === 'DOWNGRADED' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/50' :
                                                        'bg-red-500/20 text-red-400 border border-red-500/50'
                                                    }`}>
                                                    {pred.audit_verdict.status}
                                                </div>
                                            </div>
                                        </div>

                                        <div className="px-4 pt-4 pb-2 bg-gray-900/50">
                                            <div className="flex items-center gap-2 mb-2">
                                                <Search className="w-4 h-4 text-gray-400" />
                                                <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">Auditor's Internal Debate</span>
                                            </div>
                                            <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                                {pred.internal_debate}
                                            </div>
                                        </div>

                                        <div className="p-4 bg-gray-900/50 border-t border-gray-700">
                                            <div className="bg-gray-900 rounded-lg p-3 border border-gray-700">
                                                <div className="text-xs text-blue-400 font-bold mb-1 uppercase tracking-wider">Auditor Recommendation</div>
                                                <div className="flex items-center justify-between mb-2">
                                                    <div className="flex items-center gap-3">
                                                        <div className="flex -space-x-2">
                                                            {pred.home_logo && <img src={getLogoUrl(pred.home_logo)} className="w-6 h-6 rounded-full border border-gray-700 bg-white p-0.5 object-contain" alt="H" />}
                                                            {pred.away_logo && <img src={getLogoUrl(pred.away_logo)} className="w-6 h-6 rounded-full border border-gray-700 bg-white p-0.5 object-contain" alt="A" />}
                                                        </div>
                                                        <div className="text-lg font-black text-white">{pred.audit_verdict.ai_recommended_bet}</div>
                                                        {pred.audit_verdict.estimated_odds && (
                                                            <div className="text-[10px] font-black text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                                                                @{parseFloat(pred.audit_verdict.estimated_odds).toFixed(2)}
                                                            </div>
                                                        )}
                                                    </div>

                                                    {pred.audit_verdict.status !== 'REJECTED' && (
                                                        <button
                                                            onClick={() => handleAddAudit(pred)}
                                                            disabled={isAuditAdded(pred)}
                                                            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${isAuditAdded(pred)
                                                                ? 'bg-blue-500/10 text-blue-400 cursor-default border border-blue-500/20'
                                                                : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/20'
                                                                }`}
                                                        >
                                                            {isAuditAdded(pred) ? <Check className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                                                            <span>{isAuditAdded(pred) ? 'Added to Slip' : 'Add to Slip'}</span>
                                                        </button>
                                                    )}
                                                </div>
                                                <div className="text-sm mt-2 text-gray-300 italic border-l-2 border-blue-500 pl-3">
                                                    "{pred.verdict_reasoning}"
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="mt-4 border-t border-blue-900/30 pt-4">
                                        <div className="flex items-center gap-2 mb-4 text-gray-400 px-2">
                                            <Search className="w-4 h-4" />
                                            <span className="font-bold tracking-widest uppercase text-xs">Agent 1: Deep Tactical Prediction Generated Pre-Audit</span>
                                        </div>
                                        <PredictionCard prediction={pred} />
                                    </div>
                                </div>
                            ) : (
                                <PredictionCard key={i} prediction={pred} />
                            )
                        })}
                    </div>
                </main>
            )}

            {/* Admin Login Modal */}
            {showLoginModal && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                    <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-sm shadow-2xl relative">
                        <button
                            onClick={() => !loginLoading && setShowLoginModal(false)}
                            className="absolute top-4 right-4 text-gray-400 hover:text-white"
                        >
                            ×
                        </button>

                        <div className="mb-6 text-center">
                            <ShieldAlert className="w-12 h-12 text-blue-500 mx-auto mb-3" />
                            <h3 className="text-xl font-bold text-white">Admin Authentication</h3>
                            <p className="text-sm text-gray-400 mt-1">Please log in to perform this action.</p>
                        </div>

                        <form onSubmit={handleLogin} className="space-y-4">
                            {loginError && (
                                <div className="p-3 rounded bg-red-500/10 border border-red-500/20 text-red-500 text-sm text-center">
                                    {loginError}
                                </div>
                            )}

                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1">Username</label>
                                <input
                                    type="text"
                                    value={loginForm.username}
                                    onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                    required
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1">Password</label>
                                <input
                                    type="password"
                                    value={loginForm.password}
                                    onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                    required
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={loginLoading}
                                className="w-full py-2.5 rounded-lg font-bold bg-blue-600 hover:bg-blue-500 text-white flex items-center justify-center gap-2 transition-colors disabled:opacity-50 mt-4"
                            >
                                {loginLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <LogIn className="w-5 h-5" />}
                                Login
                            </button>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
