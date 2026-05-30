package com.example;

import org.hibernate.SessionFactory;

import java.util.ArrayList;
import java.util.Arrays;

import org.hibernate.Session;
import org.hibernate.cfg.Configuration;
import org.hibernate.Transaction;

// Se crean 2 laptops, un estudiante con la lista de laptops, se edita el nombre y luego se elimina al estudiante.

public class Main {
    public static void main(String[] args) {

        // Initialization
        // Config
        Configuration cfg = new Configuration();
        cfg.addAnnotatedClass(Student.class);
        cfg.addAnnotatedClass(Laptop.class);
        cfg.addAnnotatedClass(Passport.class);
        cfg.addAnnotatedClass(ClassRoom.class);
        cfg.configure();
        // Build and open session
        SessionFactory sf = cfg.buildSessionFactory();
        Session session = sf.openSession();

        // Create and save new laptops
        Laptop l1 = new Laptop(1, "HP");
        Laptop l2 = new Laptop(2, "DELL");

        // Laptops must be saved before saving the student
        try {
            Transaction transaction = session.beginTransaction();
            session.persist(l1);
            session.persist(l2);
            transaction.commit();
        } catch (Exception e) {
            System.out.println("Error saving laptops: " + e);
        }

        // Same with passsport
        Passport p1 = new Passport(1, "Argentina");
        try {
            Transaction transaction = session.beginTransaction();
            session.persist(p1);
            transaction.commit();
        } catch (Exception e) {
            System.out.println("Error saving passport: " + e);
        }

        // Same with a classRoom
        ClassRoom c1 = ClassRoom
                .builder()
                .topic("Maths")
                .students(new ArrayList<>())
                .build();
        try {
            Transaction transaction = session.beginTransaction();
            session.persist(c1);
            transaction.commit();
        } catch (Exception e) {
            System.out.println("Error saving classroom: " + e);
        }

        // Create a new student to work with
        Student s1 = Student
                .builder()
                .sname("ian")
                .sage(55)
                .passport(p1)
                .laptops(Arrays.asList(l1, l2))
                .classRooms(Arrays.asList(c1))
                .build();
        // Create
        // Save the student
        try {
            Transaction transaction = session.beginTransaction();
            session.persist(s1);
            transaction.commit();
        } catch (Exception e) {
            System.out.println("Error persisting student: " + e);
        }

        // Read
        // Load student
        Student s2 = session.find(Student.class, s1.getId());
        System.out.println("Loaded student name is: " + s2.getSname());

        // Update the before loaded student
        s2.setSname("newname");
        try {
            Transaction transaction = session.beginTransaction();
            session.merge(s2);
            transaction.commit();

        } catch (Exception e) {
            System.out.println("Error updating student: " + e);
        }

        // Delete the student
        try {
            Transaction transaction = session.beginTransaction();
            // session.remove(s2);
            transaction.commit();

        } catch (Exception e) {
            System.out.println("Error deleting student: " + e);
        }

        session.close();
        sf.close();

    }
}