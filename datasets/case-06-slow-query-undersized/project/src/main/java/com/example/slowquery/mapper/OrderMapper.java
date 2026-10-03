package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT * FROM orders " +
        "WHERE user_id = #{userId} " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Order> findOrdersByUser(@Param("userId") Long userId,
                                 @Param("size") int size);
}
