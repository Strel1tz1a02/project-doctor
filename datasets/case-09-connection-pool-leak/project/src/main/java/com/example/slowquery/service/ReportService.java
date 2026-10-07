package com.example.slowquery.service;

import org.springframework.stereotype.Service;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

@Service
public class ReportService {

    private final DataSource dataSource;

    public ReportService(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public String exportRecentOrders(int size) throws SQLException {
        Connection conn = dataSource.getConnection();
        PreparedStatement ps = conn.prepareStatement(
                "SELECT id, order_no, amount, status FROM orders ORDER BY id DESC LIMIT ?");
        ps.setInt(1, size);
        ResultSet rs = ps.executeQuery();
        StringBuilder builder = new StringBuilder();
        while (rs.next()) {
            builder.append(rs.getLong("id")).append(',')
                    .append(rs.getString("order_no")).append(',')
                    .append(rs.getBigDecimal("amount")).append(',')
                    .append(rs.getString("status")).append('\n');
        }
        return builder.toString();
    }
}
