from .query_trade import query_trade_data
from .query_rent import query_rent_data
from .query_nearby import query_trade_nearby, query_rent_nearby
from .query_commercial import query_commercial_data
from .query_district_avg import query_district_avg_price
from .predict import predict_price
from .geocode import get_station_coordinates
from .rag import search_area_info
from .anomaly import detect_anomaly

DATA_QUERY_TOOLS = [query_trade_data, query_rent_data, query_trade_nearby, query_rent_nearby, query_commercial_data, query_district_avg_price]
PREDICTION_TOOLS = [predict_price, get_station_coordinates]
RAG_TOOLS = [search_area_info]
ANOMALY_TOOLS = [detect_anomaly]
