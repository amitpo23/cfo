"""
Base integration class for external API integrations
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class BaseIntegration(ABC):
    """Base class for all external integrations"""
    
    def __init__(self, api_key: str, api_secret: Optional[str] = None, **kwargs):
        """
        Initialize the integration
        
        Args:
            api_key: API key for authentication
            api_secret: Optional API secret for authentication
            **kwargs: Additional configuration parameters
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = kwargs
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test the API connection
        
        Returns:
            bool: True if connection is successful
        """
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance information
        
        Returns:
            Dict containing balance information
        """
        pass
    
    def _log_request(self, method: str, endpoint: str, data: Optional[Dict] = None):
        """Log API request"""
        self.logger.debug(f"API Request: {method} {endpoint}", extra={"data": data})
    
    def _log_response(self, status_code: int, response: Any):
        """Log API response"""
        self.logger.debug(f"API Response: {status_code}", extra={"response": response})
    
    def _log_error(self, error: Exception, context: str = ""):
        """Log API error"""
        self.logger.error(f"API Error: {context}", exc_info=error)
