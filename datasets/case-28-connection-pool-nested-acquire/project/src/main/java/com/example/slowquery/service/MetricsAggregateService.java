package com.example.slowquery.service;

import com.example.slowquery.dto.MetricsVO;
import com.example.slowquery.mapper.MetricsMapper;
import org.springframework.stereotype.Service;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class MetricsAggregateService {

    private final DataSource dataSource;
    private final MetricsMapper metricsMapper;

    public MetricsAggregateService(DataSource dataSource, MetricsMapper metricsMapper) {
        this.dataSource = dataSource;
        this.metricsMapper = metricsMapper;
    }

    public MetricsVO aggregate(int models) throws SQLException {
        MetricsVO vo = new MetricsVO();
        try (Connection conn = dataSource.getConnection()) {
            try (PreparedStatement ps = conn.prepareStatement("SELECT COUNT(*) FROM telemetry_events");
                 ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    vo.setTotalEvents(rs.getLong(1));
                }
            }
            Map<String, Long> eventsByModel = new LinkedHashMap<>();
            for (int m = 1; m <= models; m++) {
                String model = "model-" + String.format("%02d", m);
                eventsByModel.put(model, metricsMapper.countByModel(model));
            }
            vo.setEventsByModel(eventsByModel);
        }
        return vo;
    }
}
