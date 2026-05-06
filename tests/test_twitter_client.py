import pytest
from unittest.mock import Mock, patch, MagicMock
import tweepy
from src.twitter_client import TwitterClient, post_trades_to_twitter


class TestTwitterClient:
    """Test suite for TwitterClient class."""
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_twitter_client_initialization_success(self, mock_client):
        """Test successful TwitterClient initialization."""
        client = TwitterClient()
        
        mock_client.assert_called_once_with(
            consumer_key='test_key',
            consumer_secret='test_secret',
            access_token='test_token',
            access_token_secret='test_token_secret',
            wait_on_rate_limit=True
        )
    
    @patch.dict('os.environ', {}, clear=True)
    def test_twitter_client_initialization_missing_credentials(self):
        """Test TwitterClient initialization with missing credentials."""
        with pytest.raises(ValueError, match="Missing required Twitter API credentials"):
            TwitterClient()
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_format_trade_tweet_buy(self, mock_client):
        """Test tweet formatting for BUY trade."""
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        tweet = client._format_trade_tweet(trade)
        
        assert '🚀' in tweet
        assert 'Sen. John Doe' in tweet
        assert 'just disclosed a BUY in $AAPL' in tweet
        assert 'worth up to $15k' in tweet
        assert '#CongressTrades' in tweet
        assert len(tweet) <= 280
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_format_trade_tweet_sell(self, mock_client):
        """Test tweet formatting for SELL trade."""
        client = TwitterClient()
        
        trade = {
            'firstName': 'Jane',
            'lastName': 'Smith',
            'type': 'SELL',
            'symbol': 'TSLA',
            'amount': '$50,000 - $100,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Tesla Inc - Common Stock',
            'source': 'house'
        }
        
        tweet = client._format_trade_tweet(trade)
        
        assert '⚠️' in tweet
        assert 'Rep. Jane Smith' in tweet
        assert 'just disclosed a SELL in $TSLA' in tweet
        assert 'worth up to $100k' in tweet
        assert '#CongressTrades' in tweet
        assert len(tweet) <= 280
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_format_amount_range(self, mock_client):
        """Test amount formatting for range values."""
        client = TwitterClient()
        
        # Test various amount ranges
        assert client._format_amount('$1,000 - $15,000') == 'up to $15k'
        assert client._format_amount('$1,000,000 - $5,000,000') == 'up to $5M'
        assert client._format_amount('$500 - $1,000') == 'up to $1k'
        assert client._format_amount('') == 'an undisclosed amount'
        assert client._format_amount('$15,000 - $50,000') == 'up to $50k'
        assert client._format_amount('$250,000') == '$250k'

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_format_trade_tweet_uses_amount_value_fallback(self, mock_client):
        client = TwitterClient()

        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '',
            'amount_value': 75000,
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }

        tweet = client._format_trade_tweet(trade)

        assert 'worth $75k' in tweet
        assert 'undisclosed' not in tweet.lower()
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_generate_insight_tech_buy(self, mock_client):
        """Test insight generation for tech sector BUY."""
        client = TwitterClient()
        
        trade = {'type': 'BUY', 'assetDescription': 'Apple Inc - Common Stock'}
        insight = client._generate_insight(trade)
        
        assert 'Tech sector activity could signal confidence in digital transformation.' in insight
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_generate_insight_finance_sell(self, mock_client):
        """Test insight generation for financial sector SELL."""
        client = TwitterClient()
        
        trade = {'type': 'SELL', 'assetDescription': 'JPMorgan Financial Services - Common Stock'}
        insight = client._generate_insight(trade)
        
        assert 'Banking exit could signal economic headwinds.' in insight
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_get_sector_hashtag(self, mock_client):
        """Test sector hashtag generation."""
        client = TwitterClient()
        
        assert client._get_sector_hashtag('Apple Inc - Common Stock') == '#Tech'
        assert client._get_sector_hashtag('JPMorgan Financial Services') == '#Finance'
        assert client._get_sector_hashtag('Johnson & Johnson Healthcare') == '#Healthcare'
        assert client._get_sector_hashtag('Exxon Mobil Energy Corp') == '#Energy'
        assert client._get_sector_hashtag('Lockheed Martin Defense Corp') == '#Defense'
        assert client._get_sector_hashtag('Random Company Inc') == '#Congress'
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_post_trade_tweet_success(self, mock_client):
        """Test successful tweet posting."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.create_tweet.return_value = Mock(data={'id': '123456789'})
        
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        # Should not raise an exception
        client.post_trade_tweet(trade)
        
        # Verify tweet was posted
        mock_client_instance.create_tweet.assert_called_once()

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_post_trade_tweet_rejects_incomplete_trade(self, mock_client):
        client = TwitterClient()

        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': '',
            'symbol': 'AAPL',
            'amount': '',
            'transactionDate': '2025-01-15',
        }

        with pytest.raises(ValueError, match="missing ticker, BUY/SELL direction, or disclosed amount"):
            client.post_trade_tweet(trade)

        mock_client.return_value.create_tweet.assert_not_called()

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_format_multi_trade_tweet(self, mock_client):
        """Test formatting of aggregated multi-trade tweet."""
        client = TwitterClient()

        bundle = {
            'firstName': 'Marjorie',
            'lastName': 'Greene',
            'disclosureDate': '2025-09-01',
            'trades': [
                {'type': 'purchase', 'symbol': 'EXC', 'amount': '$15,001 - $50,000'},
                {'type': 'purchase', 'symbol': 'SO', 'amount': '$1,001 - $15,000'},
            ]
        }

        tweet = client._format_multi_trade_tweet(bundle)
        assert 'just disclosed up to $65k in trades today!' in tweet
        assert '- BUY $EXC (up to $50k)' in tweet
        assert '- BUY $SO (up to $15k)' in tweet
        assert '#CongressTrades' in tweet.split('\n')[-1]
        assert tweet.count('\n') >= 3  # header + 2 bullets + hashtag line
        assert len(tweet) <= 280

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_select_trade_for_chart_prefers_best_gain(self, mock_client):
        """Ensure the bundle chart picker favors the symbol with the strongest performance."""
        client = TwitterClient()

        bundle = {
            'disclosureDate': '2025-09-01',
            'trades': [
                {'symbol': 'AAA', 'transactionDate': '2025-08-20'},
                {'symbol': 'BBB', 'transactionDate': '2025-08-21'},
                {'symbol': 'CCC', 'transactionDate': '2025-08-22'},
            ]
        }

        with patch.object(client, '_calculate_performance_since', side_effect=[5.0, 12.0, None]):
            symbol, trade_date = client._select_trade_for_chart(bundle)

        assert symbol == 'BBB'
        assert trade_date == '2025-08-21'

    @patch('src.twitter_client.TwitterClient')
    def test_post_trades_to_twitter_aggregates(self, mock_client_cls):
        """Ensure trades are aggregated by member before tweeting."""
        mock_instance = Mock()
        mock_client_cls.return_value = mock_instance

        trades = [
            {'firstName': 'Marjorie', 'lastName': 'Greene', 'disclosureDate': '2025-09-01', 'type': 'purchase', 'symbol': 'EXC', 'amount': '$1 - $2'},
            {'firstName': 'Marjorie', 'lastName': 'Greene', 'disclosureDate': '2025-09-01', 'type': 'purchase', 'symbol': 'SO', 'amount': '$3 - $4'},
            {'firstName': 'Other', 'lastName': 'Member', 'disclosureDate': '2025-09-01', 'type': 'purchase', 'symbol': 'FDX', 'amount': '$5 - $6'},
        ]

        post_trades_to_twitter(trades)

        calls = mock_instance.post_trade_tweet.call_args_list
        assert len(calls) == 2
        assert any('trades' in call[0][0] and len(call[0][0]['trades']) == 2 for call in calls)
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    @patch('src.twitter_client.time.sleep')  # Mock sleep to speed up tests
    def test_post_trade_tweet_rate_limit_retry(self, mock_sleep, mock_client):
        """Test rate limit handling with retry."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        
        # First call raises rate limit, second succeeds
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.reason = 'Too Many Requests'
        mock_response.json.return_value = {'errors': []}
        mock_client_instance.create_tweet.side_effect = [
            tweepy.TooManyRequests(mock_response),
            Mock(data={'id': '123456789'})
        ]
        
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        # Should not raise an exception (should retry and succeed)
        client.post_trade_tweet(trade)
        
        # Verify retry happened
        assert mock_client_instance.create_tweet.call_count == 2
        # First retry waits 60 seconds (there may be other tiny sleeps in the stack)
        mock_sleep.assert_any_call(60)
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    @patch('src.twitter_client.time.sleep')
    def test_post_trade_tweet_max_retries_exceeded(self, mock_sleep, mock_client):
        """Test max retries exceeded for rate limiting."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        
        # Always raise rate limit error
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.reason = 'Too Many Requests'
        mock_response.json.return_value = {'errors': []}
        mock_client_instance.create_tweet.side_effect = tweepy.TooManyRequests(mock_response)
        
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        # Should raise exception after max retries
        with pytest.raises(tweepy.TooManyRequests):
            client.post_trade_tweet(trade)
        
        # Verify all retries were attempted (4 total calls: initial + 3 retries)
        assert mock_client_instance.create_tweet.call_count == 4
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_post_trade_tweet_forbidden_error(self, mock_client):
        """Test handling of forbidden error."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.reason = 'Forbidden'
        mock_response.json.return_value = {'errors': []}
        mock_client_instance.create_tweet.side_effect = tweepy.Forbidden(mock_response)
        
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        # Should raise exception immediately (no retries for forbidden)
        with pytest.raises(tweepy.Forbidden):
            client.post_trade_tweet(trade)
        
        # Verify only one call was made (no retries)
        assert mock_client_instance.create_tweet.call_count == 1
    
    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_post_trade_tweet_unauthorized_error(self, mock_client):
        """Test handling of unauthorized error."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.reason = 'Unauthorized'
        mock_response.json.return_value = {'errors': []}
        mock_client_instance.create_tweet.side_effect = tweepy.Unauthorized(mock_response)
        
        client = TwitterClient()
        
        trade = {
            'firstName': 'John',
            'lastName': 'Doe',
            'type': 'BUY',
            'symbol': 'AAPL',
            'amount': '$1,000 - $15,000',
            'transactionDate': '2025-01-15',
            'assetDescription': 'Apple Inc - Common Stock',
            'source': 'senate'
        }
        
        # Should raise exception immediately (no retries for unauthorized)
        with pytest.raises(tweepy.Unauthorized):
            client.post_trade_tweet(trade)
        
        # Verify only one call was made (no retries)
        assert mock_client_instance.create_tweet.call_count == 1

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    def test_post_with_retry_returns_tweet_id_and_reply_target(self, mock_client):
        """Ensure _post_with_retry returns the tweet id and forwards reply target."""
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.create_tweet.return_value = Mock(data={'id': '42'})

        client = TwitterClient()
        tweet_id = client._post_with_retry("hello world", in_reply_to_tweet_id="41")

        assert tweet_id == "42"
        mock_client_instance.create_tweet.assert_called_once_with(
            text="hello world",
            in_reply_to_tweet_id="41",
        )

    @patch.dict('os.environ', {
        'TWITTER_API_KEY': 'test_key',
        'TWITTER_API_SECRET': 'test_secret',
        'TWITTER_ACCESS_TOKEN': 'test_token',
        'TWITTER_ACCESS_SECRET': 'test_token_secret'
    })
    @patch('src.twitter_client.tweepy.Client')
    @patch('src.twitter_client.time.sleep')
    def test_post_thread_builds_reply_chain(self, mock_sleep, mock_client):
        """Thread posting should chain reply ids from tweet to tweet."""
        mock_client.return_value = Mock()
        client = TwitterClient()

        parent_ids = []

        def fake_post(text, max_retries=3, media_ids=None, in_reply_to_tweet_id=None):
            parent_ids.append(in_reply_to_tweet_id)
            return str(100 + len(parent_ids) - 1)

        with patch.object(client, '_post_with_retry', side_effect=fake_post):
            ids = client.post_thread(
                [
                    {"text": "tweet one"},
                    {"text": "tweet two"},
                    {"text": "tweet three"},
                ],
                min_delay_seconds=20,
                max_delay_seconds=20,
            )

        assert ids == ["100", "101", "102"]
        assert parent_ids == [None, "100", "101"]
        assert mock_sleep.call_count == 2


class TestPostTradesToTwitter:
    """Test suite for post_trades_to_twitter function."""
    
    @patch('src.twitter_client.TwitterClient')
    @patch('src.twitter_client.time.sleep')  # Mock sleep to speed up tests
    def test_post_trades_to_twitter_success(self, mock_sleep, mock_twitter_client):
        """Test successful posting of multiple trades."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_twitter_client.return_value = mock_client_instance
        
        trades = [
            {
                'firstName': 'John',
                'lastName': 'Doe',
                'type': 'BUY',
                'symbol': 'AAPL',
                'amount': '$1,000 - $15,000',
                'transactionDate': '2025-01-15',
                'assetDescription': 'Apple Inc - Common Stock',
                'source': 'senate'
            },
            {
                'firstName': 'Jane',
                'lastName': 'Smith',
                'type': 'SELL',
                'symbol': 'TSLA',
                'amount': '$50,000 - $100,000',
                'transactionDate': '2025-01-15',
                'assetDescription': 'Tesla Inc - Common Stock',
                'source': 'house'
            }
        ]
        
        # Should not raise an exception
        post_trades_to_twitter(trades)
        
        # Verify client was created and tweets were posted
        mock_twitter_client.assert_called_once()
        assert mock_client_instance.post_trade_tweet.call_count == 2
        
        # Verify sleep was called between posts (but not after last post)
        mock_sleep.assert_called_once_with(5)
    
    @patch('src.twitter_client.TwitterClient')
    def test_post_trades_to_twitter_empty_list(self, mock_twitter_client):
        """Test posting empty trades list."""
        # Should not raise an exception and should not create client
        post_trades_to_twitter([])
        
        # Verify client was not created
        mock_twitter_client.assert_not_called()

    @patch('src.twitter_client.TwitterClient')
    def test_post_trades_to_twitter_filters_incomplete_trades(self, mock_twitter_client):
        mock_instance = Mock()
        mock_twitter_client.return_value = mock_instance

        trades = [
            {'firstName': 'John', 'lastName': 'Doe', 'type': 'purchase', 'symbol': 'AAPL', 'amount': '$1,001 - $15,000', 'disclosureDate': '2025-01-15'},
            {'firstName': 'Jane', 'lastName': 'Smith', 'type': '', 'symbol': 'TSLA', 'amount': '', 'disclosureDate': '2025-01-15'},
        ]

        post_trades_to_twitter(trades)

        mock_twitter_client.assert_called_once()
        mock_instance.post_trade_tweet.assert_called_once_with(trades[0])
    
    @patch('src.twitter_client.TwitterClient')
    def test_post_trades_to_twitter_client_error(self, mock_twitter_client):
        """Test error handling when client creation fails."""
        # Setup mock to raise exception
        mock_twitter_client.side_effect = Exception("Client creation failed")
        
        trades = [
            {
                'firstName': 'John',
                'lastName': 'Doe',
                'type': 'BUY',
                'symbol': 'AAPL',
                'amount': '$1,000 - $15,000',
                'transactionDate': '2025-01-15',
                'assetDescription': 'Apple Inc - Common Stock',
                'source': 'senate'
            }
        ]
        
        # Should raise exception
        with pytest.raises(Exception, match="Client creation failed"):
            post_trades_to_twitter(trades)
    
    @patch('src.twitter_client.TwitterClient')
    def test_post_trades_to_twitter_posting_error(self, mock_twitter_client):
        """Test error handling when tweet posting fails."""
        # Setup mock client
        mock_client_instance = Mock()
        mock_twitter_client.return_value = mock_client_instance
        mock_client_instance.post_trade_tweet.side_effect = Exception("Tweet posting failed")
        
        trades = [
            {
                'firstName': 'John',
                'lastName': 'Doe',
                'type': 'BUY',
                'symbol': 'AAPL',
                'amount': '$1,000 - $15,000',
                'transactionDate': '2025-01-15',
                'assetDescription': 'Apple Inc - Common Stock',
                'source': 'senate'
            }
        ]
        
        # Should raise exception
        with pytest.raises(Exception, match="Tweet posting failed"):
            post_trades_to_twitter(trades)


if __name__ == '__main__':
    pytest.main([__file__]) 
