package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT id, user_id, order_no, amount, status, created_at " +
        "FROM orders " +
        "WHERE status = #{status} " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Order> findOrdersByStatus(@Param("status") String status,
                                   @Param("size") int size);
}
