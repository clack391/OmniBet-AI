import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, Database, ShieldAlert, Save } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const SettingsTab = () => {
    const [provider, setProvider] = useState('football-data');
    const [geminiModel, setGeminiModel] = useState('gemini-3-pro-preview');
    const [automationEnabled, setAutomationEnabled] = useState(true);
    const [telegramMode, setTelegramMode] = useState('text');
    const [rule64Threshold, setRule64Threshold] = useState(50); // Default 50%
    const [rule64Description, setRule64Description] = useState('Balanced');
    const [rule64AutoDetect, setRule64AutoDetect] = useState(true); // Default ON
    const [cronKillSignalActive, setCronKillSignalActive] = useState(false);
    const [analysisKillSignalActive, setAnalysisKillSignalActive] = useState(false);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
        const fetchSettings = async () => {
            try {
                const providerRes = await api.get('/settings/provider');
                setProvider(providerRes.data.provider);

                const automationRes = await api.get('/settings/automation');
                setAutomationEnabled(automationRes.data.enabled);

                const telegramRes = await api.get('/settings/telegram-mode');
                setTelegramMode(telegramRes.data.mode);

                const modelRes = await api.get('/settings/gemini-model');
                setGeminiModel(modelRes.data.model);

                const killRes = await api.get('/settings/kill-active-cron');
                setCronKillSignalActive(killRes.data.kill_signal === "1");

                const analysisKillRes = await api.get('/settings/kill-active-analysis');
                setAnalysisKillSignalActive(analysisKillRes.data.kill_signal === "1");

                const rule64Res = await api.get('/settings/rule64-threshold');
                setRule64Threshold(rule64Res.data.percentage);
                setRule64Description(rule64Res.data.description);

                const rule64AutoRes = await api.get('/settings/rule64-auto-detect');
                setRule64AutoDetect(rule64AutoRes.data.enabled);
            } catch (err) {
                console.error("Failed to fetch settings", err);
            } finally {
                setLoading(false);
            }
        };
        fetchSettings();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        setMessage(null);
        try {
            await Promise.all([
                api.put('/settings/provider', { provider }),
                api.put('/settings/gemini-model', { model: geminiModel }),
                api.put('/settings/automation', { enabled: automationEnabled }),
                api.put('/settings/telegram-mode', { mode: telegramMode }),
                api.put('/settings/rule64-threshold', { threshold: rule64Threshold / 100 }),
                api.put('/settings/rule64-auto-detect', { enabled: rule64AutoDetect })
            ]);
            setMessage({ type: 'success', text: 'Settings updated successfully!' });
        } catch (err) {
            setMessage({ type: 'error', text: 'Failed to update settings.' });
            console.error(err);
        } finally {
            setSaving(false);
        }
    };

    const handleThresholdChange = (value) => {
        setRule64Threshold(value);
        // Update description based on threshold
        if (value <= 35) {
            setRule64Description('Very Conservative - Applies penalties aggressively for maximum safety');
        } else if (value <= 45) {
            setRule64Description('Conservative - Stricter analysis, safer picks, lower odds');
        } else if (value <= 55) {
            setRule64Description('Balanced - Default setting, recommended for most users');
        } else if (value <= 65) {
            setRule64Description('Aggressive - More lenient analysis, higher odds');
        } else {
            setRule64Description('Very Aggressive - Only penalizes extreme variance, maximum odds');
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6 animate-fade-in pb-12">
            <div className="bg-gray-800 rounded-xl p-4 md:p-6 shadow-lg border border-gray-700">
                <div className="flex items-center gap-3 mb-6 border-b border-gray-700 pb-4">
                    <Database className="w-6 h-6 text-teal-400" />
                    <div>
                        <h2 className="text-xl font-bold text-white">System Settings</h2>
                        <p className="text-sm text-gray-400">Manage the core API sources and automated background tasks</p>
                    </div>
                </div>

                {message && (
                    <div className={`p-4 rounded-md mb-6 ${message.type === 'success' ? 'bg-green-900/30 border border-green-500/50 text-green-300' : 'bg-red-900/30 border border-red-500/50 text-red-300'}`}>
                        {message.text}
                    </div>
                )}

                <div className="space-y-6">
                    {/* Data Provider Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-4">Primary Match Data Source</h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Option 1: Football Data */}
                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${provider === 'football-data' ? 'bg-purple-900/30 border-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="football-data"
                                            checked={provider === 'football-data'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-purple-600 bg-gray-700 border-gray-600 focus:ring-purple-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg">football-data.org</div>
                                        <div className="text-xs text-green-400 font-medium mb-2 opacity-80 mt-1 uppercase tracking-wider">Default • Stable</div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            The highly reliable, standard API used for base match statistics, fixtures, and core standings.
                                        </p>
                                    </div>
                                </div>
                            </label>

                            {/* Option 2: SofaScore / RapidAPI */}
                            <label className={`relative overflow-hidden cursor-pointer border rounded-xl p-4 transition-all ${provider === 'sofascore' ? 'bg-teal-900/30 border-teal-500 shadow-[0_0_15px_rgba(45,212,191,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4 relative z-10">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="sofascore"
                                            checked={provider === 'sofascore'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-teal-600 bg-gray-700 border-gray-600 focus:ring-teal-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg flex items-center gap-2">
                                            SofaScore (RapidAPI)
                                            <span className="bg-gradient-to-r from-orange-500 to-amber-500 text-white text-[10px] uppercase font-bold px-2 py-0.5 rounded-full">New</span>
                                        </div>
                                        <div className="text-xs text-orange-400/80 font-medium mb-2 mt-1 uppercase tracking-wider flex items-center gap-1">
                                            <ShieldAlert className="w-3 h-3" /> Experimental
                                        </div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            Aggressive data scraping pipeline bypassing football-data logic entirely to extract deep tactical metrics and advanced team statistics.
                                        </p>
                                    </div>
                                </div>
                            </label>
                        </div>
                    </div>

                    {/* Gemini AI Model Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-1">Gemini AI Model</h3>
                        <p className="text-sm text-gray-400 mb-4">Select the model used by Agent 1, Agent 2, Agent 3, and the AI Accumulator. Switch here instantly if a model goes down.</p>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {[
                                { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro Preview', badge: 'Latest', badgeColor: 'text-blue-400', desc: 'Newest generation Pro model with the latest reasoning improvements.' },
                                { value: 'gemini-3-pro-preview', label: 'Gemini 3 Pro Preview', badge: 'Default', badgeColor: 'text-green-400', desc: 'Current production model. Deep analytical reasoning and Search Grounding support.' },
                                { value: 'gemini-3-flash-preview', label: 'Gemini 3 Flash', badge: 'Fast', badgeColor: 'text-yellow-400', desc: 'Faster responses with lower latency. Good for high-volume analysis runs.' },
                                { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', badge: 'Fast', badgeColor: 'text-yellow-400', desc: 'Previous-gen flash model. Reliable fallback when newer models are unavailable.' },
                            ].map(opt => (
                                <label
                                    key={opt.value}
                                    className={`cursor-pointer border rounded-xl p-4 transition-all ${geminiModel === opt.value ? 'bg-purple-900/30 border-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}
                                >
                                    <div className="flex items-start gap-4">
                                        <div className="pt-1">
                                            <input
                                                type="radio"
                                                name="geminiModel"
                                                value={opt.value}
                                                checked={geminiModel === opt.value}
                                                onChange={(e) => setGeminiModel(e.target.value)}
                                                className="w-4 h-4 text-purple-600 bg-gray-700 border-gray-600 focus:ring-purple-500 focus:ring-2"
                                            />
                                        </div>
                                        <div>
                                            <div className="font-bold text-white">{opt.label}</div>
                                            <div className={`text-xs font-medium mb-2 mt-1 uppercase tracking-wider ${opt.badgeColor}`}>{opt.badge}</div>
                                            <p className="text-sm text-gray-400">{opt.desc}</p>
                                        </div>
                                    </div>
                                </label>
                            ))}
                        </div>
                    </div>

                    {/* Telegram Delivery Mode Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-4 flex items-center gap-2">
                            <span className="text-[#0088cc]">Telegram</span> Prediction Style
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${telegramMode === 'text' ? 'bg-blue-900/30 border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-3">
                                    <input
                                        type="radio"
                                        name="telegramMode"
                                        value="text"
                                        checked={telegramMode === 'text'}
                                        onChange={(e) => setTelegramMode(e.target.value)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-bold text-white">📝 Standard Text</div>
                                        <p className="text-xs text-gray-400 mt-1">Faster delivery with clean Markdown formatting and links.</p>
                                    </div>
                                </div>
                            </label>

                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${telegramMode === 'image' ? 'bg-indigo-900/30 border-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-3">
                                    <input
                                        type="radio"
                                        name="telegramMode"
                                        value="image"
                                        checked={telegramMode === 'image'}
                                        onChange={(e) => setTelegramMode(e.target.value)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-bold text-white">🖼️ Elite Card (Image)</div>
                                        <p className="text-xs text-gray-400 mt-1">Premium 1080x1080 social media cards based on your template.</p>
                                    </div>
                                </div>
                            </label>
                        </div>
                    </div>

                    {/* Rule 64: xG Variance Threshold Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <div className="mb-5">
                            <div className="flex items-start justify-between mb-3">
                                <div>
                                    <h3 className="text-lg font-semibold text-gray-200 mb-1 flex items-center gap-2">
                                        <span className="text-amber-400">⚡</span> Rule 64: xG Variance Threshold
                                    </h3>
                                    <p className="text-sm text-gray-400">
                                        Controls how sensitive the AI is to form variance when analyzing matches.
                                    </p>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="text-xs text-gray-400 uppercase tracking-wider">Auto-Detect</span>
                                    <button
                                        onClick={() => setRule64AutoDetect(!rule64AutoDetect)}
                                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${rule64AutoDetect ? 'bg-amber-600' : 'bg-gray-700'}`}
                                    >
                                        <span
                                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${rule64AutoDetect ? 'translate-x-6' : 'translate-x-1'}`}
                                        />
                                    </button>
                                </div>
                            </div>
                            {rule64AutoDetect && (
                                <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 mb-3">
                                    <div className="flex items-start gap-2">
                                        <span className="text-amber-400 text-sm">🤖</span>
                                        <div>
                                            <p className="text-xs text-amber-200 font-semibold mb-1">Auto-Detection Enabled</p>
                                            <p className="text-xs text-amber-300/80">
                                                AI automatically adjusts threshold per league: EPL → 35%, Azerbaijan → 65%, etc.
                                                Manual threshold below is ignored when auto-detection is ON.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}
                            {!rule64AutoDetect && (
                                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mb-3">
                                    <div className="flex items-start gap-2">
                                        <span className="text-blue-400 text-sm">✋</span>
                                        <div>
                                            <p className="text-xs text-blue-200 font-semibold mb-1">Manual Mode</p>
                                            <p className="text-xs text-blue-300/80">
                                                Your manual threshold below will be used for ALL leagues.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Slider */}
                        <div className="mb-6">
                            <div className="flex justify-between items-center mb-3">
                                <span className="text-sm font-medium text-gray-300">Sensitivity Level</span>
                                <div className="flex items-center gap-2">
                                    <span className="text-2xl font-black text-white">{rule64Threshold}%</span>
                                    <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${
                                        rule64Threshold <= 35 ? 'bg-blue-500/20 text-blue-300' :
                                        rule64Threshold <= 45 ? 'bg-green-500/20 text-green-300' :
                                        rule64Threshold <= 55 ? 'bg-amber-500/20 text-amber-300' :
                                        rule64Threshold <= 65 ? 'bg-orange-500/20 text-orange-300' :
                                        'bg-red-500/20 text-red-300'
                                    }`}>
                                        {rule64Threshold <= 35 ? 'Very Safe' :
                                         rule64Threshold <= 45 ? 'Safe' :
                                         rule64Threshold <= 55 ? 'Balanced' :
                                         rule64Threshold <= 65 ? 'Risky' : 'Very Risky'}
                                    </span>
                                </div>
                            </div>

                            <input
                                type="range"
                                min="20"
                                max="80"
                                step="5"
                                value={rule64Threshold}
                                onChange={(e) => handleThresholdChange(parseInt(e.target.value))}
                                disabled={rule64AutoDetect}
                                className={`w-full h-2 bg-gray-700 rounded-lg appearance-none slider ${rule64AutoDetect ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                                style={{
                                    background: `linear-gradient(to right,
                                        #3b82f6 0%,
                                        #10b981 ${((30-20)/(80-20))*100}%,
                                        #f59e0b ${((50-20)/(80-20))*100}%,
                                        #f97316 ${((65-20)/(80-20))*100}%,
                                        #ef4444 100%)`
                                }}
                            />

                            <div className="flex justify-between text-xs text-gray-500 mt-2">
                                <span>20% (Strict)</span>
                                <span>50% (Default)</span>
                                <span>80% (Lenient)</span>
                            </div>
                        </div>

                        {/* Description Box */}
                        <div className="bg-gray-950/50 p-4 rounded-lg border border-gray-700">
                            <div className="flex items-start gap-3">
                                <span className="text-lg">ℹ️</span>
                                <div>
                                    <p className="text-sm text-gray-300 font-medium mb-1">What this means:</p>
                                    <p className="text-xs text-gray-400 leading-relaxed">{rule64Description}</p>
                                </div>
                            </div>
                        </div>

                        {/* Examples */}
                        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-3">
                                <div className="text-xs font-bold text-blue-300 mb-1">30% (Conservative)</div>
                                <div className="text-[10px] text-gray-400">Best for: Premier League, La Liga, Bundesliga</div>
                            </div>
                            <div className="bg-amber-900/20 border border-amber-500/30 rounded-lg p-3">
                                <div className="text-xs font-bold text-amber-300 mb-1">50% (Balanced)</div>
                                <div className="text-[10px] text-gray-400">Best for: Most leagues, mixed slates</div>
                            </div>
                            <div className="bg-orange-900/20 border border-orange-500/30 rounded-lg p-3">
                                <div className="text-xs font-bold text-orange-300 mb-1">70% (Aggressive)</div>
                                <div className="text-[10px] text-gray-400">Best for: Lower leagues, volatile markets</div>
                            </div>
                        </div>
                    </div>

                    {/* AI Automation Section */}
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h3 className="text-lg font-semibold text-gray-200">Daily AI Automation</h3>
                                <p className="text-sm text-gray-400">Enable or disable the automatic 2:00 AM analysis cron job.</p>
                            </div>
                            <button
                                onClick={() => setAutomationEnabled(!automationEnabled)}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${automationEnabled ? 'bg-teal-600' : 'bg-gray-700'}`}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${automationEnabled ? 'translate-x-6' : 'translate-x-1'}`}
                                />
                            </button>
                        </div>
                        <div className="flex items-start md:items-center justify-between flex-col md:flex-row gap-4">
                            <div className="flex items-center gap-2 text-xs">
                                <span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter ${automationEnabled ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'}`}>
                                    {automationEnabled ? 'Automation Active' : 'Automation Paused'}
                                </span>
                                <span className="text-gray-500 italic">Next run scheduled for 02:00 AM WAT</span>
                            </div>

                            <div className="flex flex-col md:flex-row items-start md:items-center gap-4 w-full">
                                {/* Cron Kill Switch */}
                                <div className="flex items-center gap-3 bg-gray-900/40 p-3 rounded-lg border border-gray-700/50 flex-1 w-full justify-between">
                                    <div className="flex items-center gap-2">
                                        <div className={`w-2 h-2 rounded-full ${cronKillSignalActive ? 'bg-red-500 animate-pulse' : 'bg-green-500'}`} />
                                        <span className="text-sm font-semibold text-gray-300">Cron Kill Switch</span>
                                    </div>
                                    <button
                                        onClick={async () => {
                                            const newState = !cronKillSignalActive;
                                            if (newState && !window.confirm("Trigger Global Cron Kill Switch? This stops all automated 2AM runs.")) return;
                                            try {
                                                await api.put('/settings/kill-active-cron', { enabled: newState });
                                                setCronKillSignalActive(newState);
                                                setMessage({ type: 'success', text: newState ? 'Cron kill switch activated.' : 'Cron kill switch reset.' });
                                            } catch (err) {
                                                console.error(err);
                                            }
                                        }}
                                        className={`px-3 py-1.5 rounded-md text-[10px] font-bold transition-all ${cronKillSignalActive ? 'bg-green-600/20 text-green-500 border border-green-500/30' : 'bg-red-600/20 text-red-500 border border-red-500/30'}`}
                                    >
                                        {cronKillSignalActive ? 'RESET CRON' : 'KILL CRON'}
                                    </button>
                                </div>

                                {/* Analysis Kill Switch */}
                                <div className="flex items-center gap-3 bg-gray-900/40 p-3 rounded-lg border border-gray-700/50 flex-1 w-full justify-between">
                                    <div className="flex items-center gap-2">
                                        <div className={`w-2 h-2 rounded-full ${analysisKillSignalActive ? 'bg-red-500 animate-pulse' : 'bg-green-500'}`} />
                                        <span className="text-sm font-semibold text-gray-300">Analysis Kill Switch</span>
                                    </div>
                                    <button
                                        onClick={async () => {
                                            const newState = !analysisKillSignalActive;
                                            if (newState && !window.confirm("Trigger Global Analysis Stop? This will instantly kill all active and queued match analyses.")) return;
                                            try {
                                                await api.put('/settings/kill-active-analysis', { enabled: newState });
                                                setAnalysisKillSignalActive(newState);
                                                setMessage({ type: 'success', text: newState ? 'Active analysis terminated globally.' : 'Analysis system reset.' });
                                            } catch (err) {
                                                console.error(err);
                                            }
                                        }}
                                        className={`px-3 py-1.5 rounded-md text-[10px] font-bold transition-all ${analysisKillSignalActive ? 'bg-green-600/20 text-green-500 border border-green-500/30' : 'bg-red-600/20 text-red-500 border border-red-500/30'}`}
                                    >
                                        {analysisKillSignalActive ? 'RESET ANALYSIS' : 'KILL ANALYSIS'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="pt-4 border-t border-gray-700 flex justify-end">
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="bg-teal-600 hover:bg-teal-500 text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 shadow-lg shadow-teal-900/40"
                        >
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            {saving ? 'Saving...' : 'Save Configuration'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SettingsTab;
