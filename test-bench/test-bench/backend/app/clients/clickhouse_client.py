"""ClickHouse 客户端"""

from clickhouse_driver import Client
from typing import List, Any


class ClickHouseClient:
    """ClickHouse 客户端"""

    def __init__(self, endpoint: str, database: str, username: str = None, password: str = None):
        # 解析 host:port
        if "://" in endpoint:
            endpoint = endpoint.split("://")[-1]
        if ":" in endpoint:
            host, port = endpoint.split(":")
            port = int(port)
        else:
            host = endpoint
            port = 9000

        self.client = Client(
            host=host,
            port=port,
            database=database,
            user=username or "default",
            password=password or "",
            connect_timeout=10
        )

    def test_connection(self) -> bool:
        """测试连接"""
        try:
            self.client.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def query(self, query: str, params: tuple = None) -> List[Any]:
        """执行查询"""
        if params:
            result = self.client.execute(query, params, with_column_types=True)
        else:
            result = self.client.execute(query, with_column_types=True)

        rows = result[0]
        columns = [col[0] for col in result[1]]

        # 转换为字典列表
        dict_rows = []
        for row in rows:
            dict_rows.append(dict(zip(columns, row)))

        return dict_rows

    def close(self):
        """关闭连接"""
        self.client.disconnect()
