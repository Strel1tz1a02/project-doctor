package com.example.slowquery.service;

import com.example.slowquery.dto.StatsVO;
import com.example.slowquery.mapper.OrderStatsMapper;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class OrderStatsService {

    private final OrderStatsMapper orderStatsMapper;

    public OrderStatsService(OrderStatsMapper orderStatsMapper) {
        this.orderStatsMapper = orderStatsMapper;
    }

    public StatsVO buildStats() {
        List<String> categories = orderStatsMapper.findDistinctCategories();
        StatsVO vo = new StatsVO();
        vo.setTotalOrders(orderStatsMapper.countAll());
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String category : categories) {
            counts.put(category, orderStatsMapper.countByCategory(category));
        }
        Map<String, Long> amounts = new LinkedHashMap<>();
        for (String category : categories) {
            amounts.put(category, orderStatsMapper.sumAmountByCategory(category));
        }
        vo.setOrderCountByCategory(counts);
        vo.setAmountByCategory(amounts);
        return vo;
    }
}
