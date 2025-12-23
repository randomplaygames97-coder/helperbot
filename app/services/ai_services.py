from typing import Optional, Dict, List, Any
from functools import lru_cache
import hashlib
from datetime import datetime, timezone, timedelta
import os
from collections import defaultdict
import logging
import json
import re
from sqlalchemy.orm import Session
from app.models import SessionLocal, AIKnowledge

logger = logging.getLogger(__name__)

class AIConversationManager:
    def __init__(self):
        self.conversation_history: Dict[int, List[Dict[str, str]]] = defaultdict(list)
        self.max_history = 20
        self.user_context_cache: Dict[int, Dict[str, Any]] = {}
        self.context_cache_size = 100

    def add_message(self, ticket_id: int, role: str, content: str):
        """Add message to conversation history with timestamp"""
        history = self.conversation_history[ticket_id]
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        history.append(message)

        # Keep only recent messages
        if len(history) > self.max_history:
            history.pop(0)

    def get_context(self, ticket_id: int) -> List[Dict[str, str]]:
        """Get conversation context for AI with enhanced context awareness"""
        history = self.conversation_history[ticket_id][-10:]  # Last 10 messages

        # Add context awareness based on user behavior
        if ticket_id in self.user_context_cache:
            user_context = self.user_context_cache[ticket_id]
            context_messages = []

            # Add common issues context
            if 'common_issues' in user_context and user_context['common_issues']:
                context_messages.append({
                    "role": "system",
                    "content": f"L'utente ha avuto problemi simili in passato: {', '.join(user_context['common_issues'][:3])}"
                })

            # Add behavioral context
            if 'behavior_patterns' in user_context:
                context_messages.append({
                    "role": "system",
                    "content": f"Pattern comportamentali: {user_context['behavior_patterns']}"
                })

            return context_messages + history

        return history

    def update_user_context(self, user_id: int, issue_keywords: List[str], behavior_pattern: Optional[str] = None):
        """Update user context for better AI responses"""
        if user_id not in self.user_context_cache:
            self.user_context_cache[user_id] = {
                'common_issues': [],
                'behavior_patterns': '',
                'last_updated': datetime.now(timezone.utc)
            }

        context = self.user_context_cache[user_id]

        # Update common issues
        context['common_issues'].extend(issue_keywords)
        context['common_issues'] = list(set(context['common_issues'][-10:]))  # Keep last 10 unique issues

        # Update behavior patterns
        if behavior_pattern:
            context['behavior_patterns'] = behavior_pattern

        context['last_updated'] = datetime.now(timezone.utc)

        # Clean cache if too large
        if len(self.user_context_cache) > self.context_cache_size:
            oldest_user = min(self.user_context_cache.keys(),
                            key=lambda x: self.user_context_cache[x]['last_updated'])
            del self.user_context_cache[oldest_user]

    def clear_old_history(self, days: int = 7):
        """Clear conversation history older than specified days"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

        for ticket_id in list(self.conversation_history.keys()):
            history = self.conversation_history[ticket_id]
            # Filter out old messages
            filtered_history = [
                msg for msg in history
                if datetime.fromisoformat(msg['timestamp']) > cutoff_time
            ]

            if filtered_history:
                self.conversation_history[ticket_id] = filtered_history
            else:
                del self.conversation_history[ticket_id]

        logger.info(f"Cleared old conversation history older than {days} days")

class AIResponseCache:
    def __init__(self, max_size: int = 500):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size

    def get(self, problem_hash: str, context_hash: str) -> Optional[str]:
        """Get cached AI response"""
        cache_key = f"{problem_hash}:{context_hash}"
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            # Check if cache entry is still valid (24 hours)
            if datetime.now(timezone.utc) - datetime.fromisoformat(entry['timestamp']) < timedelta(hours=24):
                return entry['response']
            else:
                # Remove expired entry
                del self.cache[cache_key]
        return None

    def set(self, problem_hash: str, context_hash: str, response: str):
        """Cache AI response"""
        cache_key = f"{problem_hash}:{context_hash}"

        # Clean cache if too large
        if len(self.cache) >= self.max_size:
            # Remove oldest entries
            oldest_keys = sorted(self.cache.keys(),
                               key=lambda k: self.cache[k]['timestamp'])[:50]
            for key in oldest_keys:
                del self.cache[key]

        self.cache[cache_key] = {
            'response': response,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

# Global AI response cache
ai_response_cache = AIResponseCache()

class LearningSystem:
    def __init__(self):
        self.db_session = None

    def _get_session(self) -> Session:
        """Get database session, initializing if needed"""
        if self.db_session is None:
            if SessionLocal is None:
                raise RuntimeError("Database session not initialized")
            self.db_session = SessionLocal()
        return self.db_session

    def extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text using regex patterns"""
        # Common Italian keywords for the bot's domain
        keywords = []

        # Convert to lowercase for matching
        text_lower = text.lower()

        # Extract words longer than 3 characters, excluding common stop words
        stop_words = {'il', 'la', 'lo', 'i', 'gli', 'le', 'un', 'una', 'uno', 'di', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra', 'che', 'chi', 'come', 'dove', 'quando', 'perché', 'cosa', 'quale', 'quanto', 'e', 'o', 'ma', 'se', 'non', 'si', 'no', 'sì', 'io', 'tu', 'lui', 'lei', 'noi', 'voi', 'loro'}
        words = re.findall(r'\b\w{4,}\b', text_lower)
        keywords.extend([word for word in words if word not in stop_words])

        # Extract specific patterns like dates, numbers, etc.
        # Add domain-specific keywords
        domain_keywords = ['lista', 'list', 'rinnovo', 'renewal', 'scadenza', 'expiry', 'ticket', 'supporto', 'aiuto', 'problema', 'errore', 'notifica', 'notification', 'cancellazione', 'deletion', 'richiesta', 'request']
        for keyword in domain_keywords:
            if keyword in text_lower:
                keywords.append(keyword)

        return list(set(keywords))  # Remove duplicates

    def find_matching_patterns(self, keywords: List[str], threshold: float = 0.3) -> List[Dict[str, Any]]:
        """Find matching patterns in AI knowledge base"""
        try:
            session = self._get_session()
            all_knowledge = session.query(AIKnowledge).all()
            matches = []

            for knowledge in all_knowledge:
                stored_keywords = json.loads(knowledge.keywords) if knowledge.keywords else []
                # Calculate similarity based on keyword overlap
                intersection = set(keywords) & set(stored_keywords)
                union = set(keywords) | set(stored_keywords)
                if union:
                    similarity = len(intersection) / len(union)
                    if similarity >= threshold:
                        matches.append({
                            'id': knowledge.id,
                            'problem_key': knowledge.problem_key,
                            'solution_text': knowledge.solution_text,
                            'success_count': knowledge.success_count,
                            'similarity': similarity,
                            'keywords': stored_keywords
                        })

            # Sort by success_count and similarity
            matches.sort(key=lambda x: (x['success_count'], x['similarity']), reverse=True)
            return matches[:5]  # Return top 5 matches

        except Exception as e:
            logger.error(f"Error finding matching patterns: {e}")
            return []

    def learn_from_ticket(self, problem_description: str, solution_text: str):
        """Learn from a resolved ticket"""
        try:
            session = self._get_session()
            keywords = self.extract_keywords(problem_description)
            problem_key = '_'.join(sorted(keywords[:3]))  # Create a key from top keywords

            # Check if similar knowledge already exists
            existing = session.query(AIKnowledge).filter_by(problem_key=problem_key).first()

            if existing:
                # Update existing knowledge
                existing.solution_text = solution_text
                existing.success_count += 1
                existing.keywords = json.dumps(keywords)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                # Create new knowledge entry
                new_knowledge = AIKnowledge(
                    problem_key=problem_key,
                    solution_text=solution_text,
                    success_count=1,
                    keywords=json.dumps(keywords)
                )
                session.add(new_knowledge)

            session.commit()
            logger.info(f"Learned from ticket: {problem_key}")

        except Exception as e:
            logger.error(f"Error learning from ticket: {e}")
            if self.db_session:
                self.db_session.rollback()

    def get_response(self, problem_description: str) -> Optional[str]:
        """Generate response based on learned patterns"""
        try:
            keywords = self.extract_keywords(problem_description)
            matches = self.find_matching_patterns(keywords)

            if matches:
                # Use the best match
                best_match = matches[0]
                response = f"Basandomi su esperienze precedenti, ecco una possibile soluzione:\n\n{best_match['solution_text']}\n\nQuesta soluzione ha funzionato {best_match['success_count']} volta/e."
                return response
            else:
                return "Non ho ancora una soluzione specifica per questo problema. Un amministratore ti assisterà presto."

        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Si è verificato un errore nel generare la risposta. Un amministratore ti assisterà presto."

@lru_cache(maxsize=100)
def get_cached_ai_response(problem_hash: str, context_hash: str) -> Optional[str]:
    """Cache AI responses based on problem and context"""
    return ai_response_cache.get(problem_hash, context_hash)

def generate_content_hash(content: str) -> str:
    """Generate hash for content caching"""
    return hashlib.md5(content.encode()).hexdigest()

class EnhancedAIService:
    def __init__(self):
        self.conversation_manager = AIConversationManager()
        self.learning_system = LearningSystem()

    def get_ai_response(self, problem_description: str, is_followup: bool = False, ticket_id: Optional[int] = None, user_id: Optional[int] = None) -> Optional[str]:
        """Get AI response using learning system"""
        try:
            # Use learning system to get response
            response = self.learning_system.get_response(problem_description)

            # Update conversation context if ticket_id provided
            if ticket_id:
                self.conversation_manager.add_message(ticket_id, "user", problem_description)
                self.conversation_manager.add_message(ticket_id, "assistant", response or "")

            return response

        except Exception as e:
            logger.error(f"Error in get_ai_response: {e}")
            return "Si è verificato un errore nel sistema di supporto. Un amministratore ti assisterà presto."

    def learn_from_ticket(self, problem_description: str, solution_text: str):
        """Learn from a resolved ticket"""
        self.learning_system.learn_from_ticket(problem_description, solution_text)

# Global AI service instance
ai_service = EnhancedAIService()
