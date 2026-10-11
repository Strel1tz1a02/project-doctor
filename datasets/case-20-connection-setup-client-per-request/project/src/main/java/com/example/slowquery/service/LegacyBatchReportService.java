package com.example.slowquery.service;

import org.springframework.stereotype.Service;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

@Service
public class LegacyBatchReportService {

    private static final String URL = "jdbc:mysql://localhost:3306/batch_demo?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&useSSL=false";
    private static final String USER = "root";
    private static final String PASSWORD = "root";

    public String loadBatch(int size) {
        StringBuilder builder = new StringBuilder();
        try (Connection conn = DriverManager.getConnection(URL, USER, PASSWORD);
             PreparedStatement ps = conn.prepareStatement("SELECT id, order_no, amount FROM orders ORDER BY id DESC LIMIT ?")) {
            ps.setInt(1, size);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    builder.append(rs.getLong("id"))
                            .append(",")
                            .append(rs.getString("order_no"))
                            .append(",")
                            .append(rs.getBigDecimal("amount"))
                            .append("\n");
                }
            }
        } catch (Exception e) {
            throw new RuntimeException("legacy batch report query failed", e);
        }
        return builder.toString();
    }
}
