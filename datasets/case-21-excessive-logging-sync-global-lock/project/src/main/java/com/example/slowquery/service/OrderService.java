package com.example.slowquery.service;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.log.AuditLogger;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class OrderService {

    private final OrderMapper orderMapper;
    private final AuditLogger auditLogger;

    public OrderService(OrderMapper orderMapper, AuditLogger auditLogger) {
        this.orderMapper = orderMapper;
        this.auditLogger = auditLogger;
    }

    public List<OrderVO> auditReport(Long userId, int size) {
        List<Order> orders = orderMapper.findOrdersByUser(userId, size);
        List<OrderVO> result = new ArrayList<>();

        for (Order order : orders) {
            auditLogger.log("order row: id=" + order.getId()
                    + ", orderNo=" + order.getOrderNo()
                    + ", amount=" + order.getAmount()
                    + ", status=" + order.getStatus());
            OrderVO vo = new OrderVO();
            vo.setOrderId(order.getId());
            vo.setOrderNo(order.getOrderNo());
            vo.setAmount(order.getAmount());
            vo.setStatus(order.getStatus());
            vo.setCreatedAt(order.getCreatedAt());
            result.add(vo);
        }

        return result;
    }
}
