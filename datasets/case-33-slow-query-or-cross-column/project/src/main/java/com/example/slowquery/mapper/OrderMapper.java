package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT id, user_id, status, amount, created_at_ms " +
        "FROM orders " +
        "WHERE user_id = #{userId} OR status = #{status} " +
        "ORDER BY created_at_ms DESC " +
        "LIMIT #{limit}"
    )
    List<Order> findOrdersByUserOrStatus(@Param("userId") long userId,
                                         @Param("status") String status,
                                         @Param("limit") int limit);
}
